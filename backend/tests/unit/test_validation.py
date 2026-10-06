import asyncio
import hashlib
import unicodedata

import pytest

from app.errors import AppError
from app.services.validation import (
    MAX_UPLOAD_BYTES,
    MULTIPART_OVERHEAD_BYTES,
    read_upload,
    sanitize_filename,
    validate_upload,
)

PDF = b"%PDF-1.4\n%test\n"
BOUNDARY = "----cvtestboundary"


def multipart(*parts: tuple[str, str | None, bytes]) -> bytes:
    """Build a multipart/form-data body from (field name, filename or None, data) parts."""
    out = bytearray()
    for name, filename, data in parts:
        disposition = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename is not None else "")
        out += f"--{BOUNDARY}\r\nContent-Disposition: {disposition}\r\n".encode()
        out += b"Content-Type: application/octet-stream\r\n\r\n" + data + b"\r\n"
    out += f"--{BOUNDARY}--\r\n".encode()
    return bytes(out)


class FakeRequest:
    """Minimal stand-in for starlette Request: headers + chunked async body stream."""

    def __init__(self, body: bytes, chunk: int = 7919, content_type: str | None = None, length: bool = True):
        self.headers = {"content-type": content_type or f"multipart/form-data; boundary={BOUNDARY}"}
        if length:
            self.headers["content-length"] = str(len(body))
        self._body, self._chunk = body, chunk
        self.consumed = 0

    async def stream(self):
        for i in range(0, len(self._body), self._chunk):
            piece = self._body[i : i + self._chunk]
            self.consumed += len(piece)
            yield piece


def read(req, **kw):
    return asyncio.run(read_upload(req, **kw))


def read_error(req, **kw):
    with pytest.raises(AppError) as exc:
        read(req, **kw)
    return exc.value.status, exc.value.code


def code_of(fn, *args):
    with pytest.raises(AppError) as exc:
        fn(*args)
    return exc.value.status, exc.value.code


def test_v1_normal_filename():
    assert sanitize_filename("report.pdf") == "report.pdf"


def test_v2_path_traversal():
    assert sanitize_filename("../../etc/passwd.txt") == "passwd.txt"


def test_v3_backslash_path():
    assert sanitize_filename("..\\..\\x.pdf") == "x.pdf"


def test_v4_control_chars_removed():
    assert sanitize_filename("a\x00b\x1f.pdf") == "ab.pdf"


def test_v5_long_name_rejected():
    assert code_of(sanitize_filename, "a" * 296 + ".pdf") == (422, "INVALID_FILENAME")
    assert sanitize_filename("a" * 146 + ".pdf") == "a" * 146 + ".pdf"


def test_v6_unicode_nfc():
    decomposed = unicodedata.normalize("NFD", "résumé 日本.pdf")
    result = sanitize_filename(decomposed)
    assert result == unicodedata.normalize("NFC", "résumé 日本.pdf")
    assert validate_upload(decomposed, PDF).display_name == result


@pytest.mark.parametrize("name", ["", "   ", ".", "..", "dir/", "\x00", None])
def test_empty_or_dot_names_rejected(name):
    assert code_of(sanitize_filename, name) == (422, "INVALID_FILENAME")


def test_v7_empty_file():
    assert code_of(validate_upload, "a.pdf", b"") == (400, "EMPTY_FILE")


def test_empty_checked_before_filename():
    assert code_of(validate_upload, "..", b"") == (400, "EMPTY_FILE")


def test_v8_size_boundary_stream():
    ok = read(FakeRequest(multipart(("file", "a.txt", b"a" * MAX_UPLOAD_BYTES)), chunk=65536))
    assert len(ok.data) == MAX_UPLOAD_BYTES
    assert validate_upload(ok.filename, ok.data).size_bytes == MAX_UPLOAD_BYTES

    over = FakeRequest(multipart(("file", "a.txt", b"a" * (MAX_UPLOAD_BYTES + 1))), chunk=65536, length=False)
    assert read_error(over) == (413, "FILE_TOO_LARGE")


def test_cap_enforced_while_streaming_not_after():
    req = FakeRequest(multipart(("file", "a.txt", b"a" * 5000)), chunk=100, length=False)
    assert read_error(req, limit=1000) == (413, "FILE_TOO_LARGE")
    assert req.consumed < 1500


def test_declared_content_length_over_cap_rejected_before_reading():
    big = FakeRequest(multipart(("file", "a.txt", b"a" * (MULTIPART_OVERHEAD_BYTES + 2000))))
    assert read_error(big, limit=1000) == (413, "FILE_TOO_LARGE")
    assert big.consumed == 0


def test_reads_file_part_split_across_tiny_chunks():
    body = multipart(("note", None, b"ignored"), ("file", "r\u00e9sum\u00e9.pdf", PDF))
    got = read(FakeRequest(body, chunk=3))
    assert got.filename == "r\u00e9sum\u00e9.pdf"
    assert got.data == PDF


def test_missing_file_field():
    assert read_error(FakeRequest(multipart(("other", "a.pdf", PDF)))) == (422, "VALIDATION_ERROR")


def test_file_field_must_be_a_file():
    assert read_error(FakeRequest(multipart(("file", None, b"text")))) == (422, "VALIDATION_ERROR")


def test_duplicate_file_field_rejected():
    body = multipart(("file", "a.pdf", PDF), ("file", "b.pdf", PDF))
    assert read_error(FakeRequest(body)) == (422, "VALIDATION_ERROR")


def test_not_multipart_rejected():
    assert read_error(FakeRequest(b"{}", content_type="application/json")) == (422, "VALIDATION_ERROR")


def test_malformed_body_rejected():
    assert read_error(FakeRequest(b"garbage without boundaries")) == (422, "VALIDATION_ERROR")


def test_empty_file_part_reads_as_empty_then_fails_validation():
    got = read(FakeRequest(multipart(("file", "a.pdf", b""))))
    with pytest.raises(AppError) as exc:
        validate_upload(got.filename, got.data)
    assert exc.value.code == "EMPTY_FILE"


def test_v9_wrong_magic():
    assert code_of(validate_upload, "a.pdf", b"just text") == (415, "UNSUPPORTED_TYPE")


def test_v10_disallowed_extension():
    assert code_of(validate_upload, "a.exe", b"MZ\x90\x00") == (415, "UNSUPPORTED_TYPE")
    assert code_of(validate_upload, "noext", b"hello") == (415, "UNSUPPORTED_TYPE")


@pytest.mark.parametrize(
    ("name", "data", "content_type"),
    [
        ("a.PDF", PDF, "application/pdf"),
        ("a.png", b"\x89PNG\r\n\x1a\n...", "image/png"),
        ("a.jpg", b"\xff\xd8\xff\xe0", "image/jpeg"),
        ("a.jpeg", b"\xff\xd8\xff\xe0", "image/jpeg"),
        ("a.docx", b"PK\x03\x04rest", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("a.txt", "héllo".encode(), "text/plain"),
        ("a.md", b"# hi", "text/markdown"),
        ("a.csv", b"a,b\n1,2", "text/csv"),
    ],
)
def test_allowed_types_and_content_type_map(name, data, content_type):
    v = validate_upload(name, data)
    assert v.content_type == content_type
    assert v.sha256 == hashlib.sha256(data).hexdigest()


def test_text_with_nul_rejected():
    assert code_of(validate_upload, "a.txt", b"a\x00b") == (415, "UNSUPPORTED_TYPE")


def test_text_invalid_utf8_rejected():
    assert code_of(validate_upload, "a.csv", b"\xff\xfe") == (415, "UNSUPPORTED_TYPE")
