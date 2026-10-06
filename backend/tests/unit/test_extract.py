"""T16: extraction module (doc 08.2/08.3 rules). Doc 10.2 L1, L2, plus encrypted PDF, docx, image."""

import io
import zipfile

import pytest
from pypdf import PdfWriter

from app.processing import extract as extract_module
from app.processing.extract import DOCX, MAX_EXCERPT_CHARS, MAX_PROCESS_BYTES, PDF, extract


def make_pdf(pages: list[str]) -> bytes:
    """A small, valid PDF with real text, built with a correct cross-reference table."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    page_ids = [3 + 2 * i for i in range(len(pages))]
    font_id = 3 + 2 * len(pages)
    objects.append(f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {len(pages)} >>")
    for i, text in enumerate(pages):
        content = f"BT /F1 12 Tf 72 712 Td ({text}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {page_ids[i] + 1} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        )
        objects.append(f"<< /Length {len(content)} >>\nstream\n{content.decode()}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n{body}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_docx(paragraphs: list[str]) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


# ---- success paths ----

def test_pdf_pages_words_and_excerpt():
    r = extract(PDF, make_pdf(["Quarterly budget review", "Second page here"]))
    assert (r.status, r.error_code, r.page_count) == ("SUCCEEDED", None, 2)
    assert r.word_count == 6
    assert r.text_excerpt == "Quarterly budget review Second page here"


def test_docx_words_and_excerpt():
    r = extract(DOCX, make_docx(["Hello CloudVault", "simulated S3 storage"]))
    assert (r.status, r.page_count, r.word_count) == ("SUCCEEDED", None, 5)
    assert r.text_excerpt == "Hello CloudVault simulated S3 storage"


@pytest.mark.parametrize("content_type", ["text/plain", "text/markdown", "text/csv"])
def test_text_types(content_type):
    r = extract(content_type, b"a,b\n1, 2\n\n  three   words here ")
    assert (r.status, r.word_count, r.page_count) == ("SUCCEEDED", 6, None)
    assert r.text_excerpt == "a,b 1, 2 three words here"


def test_excerpt_is_capped():
    r = extract("text/plain", ("word " * 5000).encode())
    assert len(r.text_excerpt) == MAX_EXCERPT_CHARS and r.word_count == 5000


def test_empty_text_has_no_excerpt():
    r = extract("text/plain", b"   \n ")
    assert (r.status, r.word_count, r.text_excerpt) == ("SUCCEEDED", 0, None)


# ---- deterministic skips and failures (doc 08.3) ----

def test_l1_oversized_object_is_skipped_without_parsing(monkeypatch):
    monkeypatch.setattr(extract_module, "_extract_pdf", lambda data: pytest.fail("parsed an oversized object"))
    r = extract("text/plain", b"a" * (6 * 1024 * 1024))
    assert (r.status, r.error_code) == ("SKIPPED", "TOO_LARGE")
    assert extract(PDF, b"%PDF-", size_bytes=MAX_PROCESS_BYTES + 1).error_code == "TOO_LARGE"
    assert extract("text/plain", b"a" * MAX_PROCESS_BYTES).status == "SUCCEEDED"  # boundary is inclusive


def test_l2_corrupt_pdf_fails_deterministically():
    r = extract(PDF, b"%PDF-1.4\nthis is not really a pdf")
    assert (r.status, r.error_code) == ("FAILED", "CORRUPT")
    assert len(r.error_message) <= 500


def test_encrypted_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secret")
    buf = io.BytesIO()
    writer.write(buf)
    r = extract(PDF, buf.getvalue())
    assert (r.status, r.error_code) == ("FAILED", "ENCRYPTED")


@pytest.mark.parametrize("content_type", ["image/png", "image/jpeg"])
def test_images_are_skipped(content_type):
    r = extract(content_type, b"\x89PNG\r\n\x1a\n...")
    assert (r.status, r.error_code) == ("SKIPPED", "NO_EXTRACTION")


@pytest.mark.parametrize(
    "data",
    [b"PK\x03\x04 not a zip", None],  # None: a valid zip without word/document.xml
)
def test_corrupt_docx(data):
    if data is None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("other.xml", "<x/>")
        data = buf.getvalue()
    assert extract(DOCX, data).error_code == "CORRUPT"


def test_docx_with_broken_xml():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document><unclosed>")
    assert extract(DOCX, buf.getvalue()).error_code == "CORRUPT"


def test_docx_expanding_beyond_the_cap_is_skipped(monkeypatch):
    monkeypatch.setattr(extract_module, "MAX_DOCX_XML_BYTES", 1000)
    r = extract(DOCX, make_docx(["x" * 5000]))  # compresses tiny, expands past the cap
    assert (r.status, r.error_code) == ("SKIPPED", "TOO_LARGE")


def test_unexpected_parser_error_is_parse_error(monkeypatch):
    def boom(data):
        raise ValueError("internal parser bug")

    monkeypatch.setattr(extract_module, "_extract_pdf", boom)
    r = extract(PDF, b"%PDF-1.4")
    assert (r.status, r.error_code) == ("FAILED", "PARSE_ERROR")
    assert "internal parser bug" not in r.error_message  # no internal details recorded


def test_unknown_type_is_not_processed():
    assert extract("application/octet-stream", b"x").error_code == "NO_EXTRACTION"
