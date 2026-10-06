"""Document text extraction (doc 08.2/08.3 rules, run by the in-process worker; AM-7).

Pure functions over bytes and a content type: no I/O, no database, no storage. The worker
(T17) reads the stored object and records the result. Outcomes follow doc 08.3:

  extraction succeeded        SUCCEEDED
  object over the size gate   SKIPPED  TOO_LARGE      (bytes never parsed)
  image types                 SKIPPED  NO_EXTRACTION
  corrupt / unparseable       FAILED   CORRUPT
  encrypted PDF               FAILED   ENCRYPTED
  any other parsing error     FAILED   PARSE_ERROR

All of these are deterministic: the worker records them and never retries them.
"""

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from typing import Literal
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger("cloudvault.processing")

MAX_PROCESS_BYTES = 5_242_880  # doc 08.2 size gate (MAX_PROCESS_BYTES)
MAX_EXCERPT_CHARS = 4000  # doc 04 processing_jobs.text_excerpt
MAX_ERROR_CHARS = 500  # doc 04 processing_jobs.error_message
# A .docx is a zip; bound the decompressed XML so a tiny archive cannot expand without limit.
MAX_DOCX_XML_BYTES = 50 * 1024 * 1024

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_TYPES = frozenset({"text/plain", "text/markdown", "text/csv"})
IMAGE_TYPES = frozenset({"image/png", "image/jpeg"})
_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WORDS = re.compile(r"\S+")
_SPACE = re.compile(r"\s+")

Status = Literal["SUCCEEDED", "FAILED", "SKIPPED"]


@dataclass(frozen=True)
class ExtractionResult:
    status: Status
    error_code: str | None = None
    error_message: str | None = None
    page_count: int | None = None
    word_count: int | None = None
    text_excerpt: str | None = None


def _succeeded(text: str, page_count: int | None = None) -> ExtractionResult:
    excerpt = _SPACE.sub(" ", text).strip()[:MAX_EXCERPT_CHARS]
    return ExtractionResult(
        status="SUCCEEDED",
        page_count=page_count,
        word_count=len(_WORDS.findall(text)),
        text_excerpt=excerpt or None,
    )


def _outcome(status: Status, code: str, message: str) -> ExtractionResult:
    return ExtractionResult(status=status, error_code=code, error_message=message[:MAX_ERROR_CHARS])


def extract(
    content_type: str, data: bytes, size_bytes: int | None = None, max_bytes: int = MAX_PROCESS_BYTES
) -> ExtractionResult:
    """Extract counts and an excerpt. `size_bytes` (the stored size) lets the gate run before any read."""
    size = len(data) if size_bytes is None else size_bytes
    if size > max_bytes or len(data) > max_bytes:
        return _outcome("SKIPPED", "TOO_LARGE", f"Larger than the {max_bytes}-byte processing limit")
    if content_type in IMAGE_TYPES:
        return _outcome("SKIPPED", "NO_EXTRACTION", "Images are not processed")
    try:
        if content_type == PDF:
            return _extract_pdf(data)
        if content_type == DOCX:
            return _extract_docx(data)
        if content_type in TEXT_TYPES:
            return _succeeded(data.decode("utf-8", errors="replace"))
    except Exception as exc:  # unexpected parser failure: deterministic, recorded, not retried
        logger.warning("Extraction failed for %s: %s", content_type, type(exc).__name__)
        return _outcome("FAILED", "PARSE_ERROR", f"Could not parse the file ({type(exc).__name__})")
    return _outcome("SKIPPED", "NO_EXTRACTION", f"No extractor for {content_type}")


def _extract_pdf(data: bytes) -> ExtractionResult:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return _outcome("FAILED", "ENCRYPTED", "The PDF is encrypted")
        pages = reader.pages
        page_count = len(pages)
    except PdfReadError as exc:
        return _outcome("FAILED", "CORRUPT", f"The PDF is damaged or unreadable ({exc})")
    text = "\n".join(page.extract_text() or "" for page in pages)
    return _succeeded(text, page_count=page_count)


def _extract_docx(data: bytes) -> ExtractionResult:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        info = archive.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        return _outcome("FAILED", "CORRUPT", f"Not a readable Word document ({type(exc).__name__})")
    if info.file_size > MAX_DOCX_XML_BYTES:
        return _outcome("SKIPPED", "TOO_LARGE", "The document's text is too large to process")
    with archive.open(info) as handle:
        xml = handle.read(MAX_DOCX_XML_BYTES + 1)
    if len(xml) > MAX_DOCX_XML_BYTES:  # the header lied about the size
        return _outcome("SKIPPED", "TOO_LARGE", "The document's text is too large to process")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        return _outcome("FAILED", "CORRUPT", f"The document XML is damaged ({exc})")
    paragraphs = [
        "".join(node.text or "" for node in para.iter(f"{_WORD_NS}t")) for para in root.iter(f"{_WORD_NS}p")
    ]
    return _succeeded("\n".join(paragraphs))
