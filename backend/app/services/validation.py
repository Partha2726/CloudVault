"""Upload validation (doc 05.3). Checks run in the documented order.

The sanitized filename is only ever a display name. It never becomes an S3 key or a
filesystem path, and nothing here writes to disk.
"""

import hashlib
import os
import unicodedata
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Protocol

from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header

from app.errors import AppError

MAX_UPLOAD_BYTES = 10_485_760
MAX_FILENAME_CHARS = 150
# Room for multipart boundaries and part headers on top of the file bytes.
MULTIPART_OVERHEAD_BYTES = 64 * 1024

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
TEXT_EXTENSIONS = {".txt", ".md", ".csv"}
MAGIC_BYTES = {
    ".pdf": b"%PDF-",
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".docx": b"PK\x03\x04",
}


class StreamingRequest(Protocol):
    """The parts of a Starlette `Request` the reader needs (kept small for tests)."""

    @property
    def headers(self) -> Mapping[str, str]: ...

    def stream(self) -> AsyncIterator[bytes]: ...


@dataclass(frozen=True)
class UploadedFile:
    filename: str | None
    data: bytes


@dataclass(frozen=True)
class ValidatedFile:
    data: bytes
    display_name: str
    content_type: str
    sha256: str

    @property
    def size_bytes(self) -> int:
        return len(self.data)


def _too_large(limit: int) -> AppError:
    return AppError("FILE_TOO_LARGE", 413, f"File exceeds the {limit}-byte limit")


def _bad_request(message: str) -> AppError:
    return AppError("VALIDATION_ERROR", 422, message)


class _FilePartCollector:
    """python-multipart callbacks that keep only the `file` field, in memory, capped at limit + 1."""

    def __init__(self, field: str, limit: int):
        self.field = field
        self.limit = limit
        self.data = bytearray()
        self.filename: str | None = None
        self.found = False
        self._in_target = False
        self._header_field = bytearray()
        self._header_value = bytearray()
        self._disposition: bytes | None = None

    def callbacks(self) -> dict:
        return {
            "on_part_begin": self._part_begin,
            "on_header_field": lambda d, s, e: self._header_field.extend(d[s:e]),
            "on_header_value": lambda d, s, e: self._header_value.extend(d[s:e]),
            "on_header_end": self._header_end,
            "on_headers_finished": self._headers_finished,
            "on_part_data": self._part_data,
        }

    def _part_begin(self) -> None:
        self._in_target = False
        self._disposition = None

    def _header_end(self) -> None:
        if bytes(self._header_field).lower() == b"content-disposition":
            self._disposition = bytes(self._header_value)
        self._header_field.clear()
        self._header_value.clear()

    def _headers_finished(self) -> None:
        if self._disposition is None:
            return
        _, params = parse_options_header(self._disposition)
        if params.get(b"name", b"").decode("utf-8", "replace") != self.field:
            return
        if self.found:
            raise _bad_request(f"Only one '{self.field}' part is allowed")
        if b"filename" not in params:
            raise _bad_request(f"'{self.field}' must be a file")
        self.found = self._in_target = True
        self.filename = params[b"filename"].decode("utf-8", "replace")

    def _part_data(self, data: bytes, start: int, end: int) -> None:
        if not self._in_target:
            return
        room = self.limit + 1 - len(self.data)
        self.data.extend(data[start : start + min(end - start, room)])
        if len(self.data) > self.limit:
            raise _too_large(self.limit)


async def read_upload(request: StreamingRequest, field: str = "file", limit: int = MAX_UPLOAD_BYTES) -> UploadedFile:
    """Stream a multipart/form-data body and return the `field` file part (doc 05.3 step 1).

    Replaces FastAPI's `UploadFile`, which spools parts over 1 MB to a temporary file on
    disk (AGENTS.md rule 7). Bytes stay in memory; the file part never exceeds limit + 1
    bytes and the whole body is capped at limit + MULTIPART_OVERHEAD_BYTES.
    """
    content_type, params = parse_options_header(request.headers.get("content-type", ""))
    boundary = params.get(b"boundary")
    if content_type != b"multipart/form-data" or not boundary:
        raise _bad_request("Expected multipart/form-data with a 'file' field")

    body_limit = limit + MULTIPART_OVERHEAD_BYTES
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > body_limit:
        raise _too_large(limit)

    collector = _FilePartCollector(field, limit)
    parser = MultipartParser(boundary, collector.callbacks())
    received = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > body_limit:
                raise _too_large(limit)
            parser.write(chunk)
        parser.finalize()
    except MultipartParseError as exc:
        raise _bad_request("Malformed multipart body") from exc
    if not collector.found:
        raise _bad_request(f"Missing '{field}' file field")
    return UploadedFile(filename=collector.filename, data=bytes(collector.data))


def sanitize_filename(raw: str | None) -> str:
    name = unicodedata.normalize("NFC", raw or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch) != "Cc")
    name = name.strip()
    if name in ("", ".", ".."):
        raise AppError("INVALID_FILENAME", 422, "Filename is empty or invalid")
    if len(name) > MAX_FILENAME_CHARS:
        raise AppError("INVALID_FILENAME", 422, f"Filename is longer than {MAX_FILENAME_CHARS} characters")
    return name


def _unsupported(message: str) -> AppError:
    return AppError("UNSUPPORTED_TYPE", 415, message)


def _check_content(ext: str, data: bytes) -> None:
    if ext in TEXT_EXTENSIONS:
        if b"\x00" in data:
            raise _unsupported("Text file contains NUL bytes")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _unsupported("Text file is not valid UTF-8") from exc
    elif not data.startswith(MAGIC_BYTES[ext]):
        raise _unsupported("File content does not match its extension")


def validate_upload(filename: str | None, data: bytes, limit: int = MAX_UPLOAD_BYTES) -> ValidatedFile:
    """Doc 05.3 steps 2-7 on bytes from `read_upload`. The client's Content-Type is ignored."""
    if len(data) > limit:
        raise _too_large(limit)
    if not data:
        raise AppError("EMPTY_FILE", 400, "File is empty")
    display_name = sanitize_filename(filename)
    ext = os.path.splitext(display_name)[1].lower()
    if ext not in CONTENT_TYPES:
        raise _unsupported("File type is not allowed")
    _check_content(ext, data)
    return ValidatedFile(
        data=data,
        display_name=display_name,
        content_type=CONTENT_TYPES[ext],
        sha256=hashlib.sha256(data).hexdigest(),
    )
