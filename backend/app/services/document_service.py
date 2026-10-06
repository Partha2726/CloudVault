"""Document upload (W2), listing (W7), detail, download links (W3) and access log (W9).

Upload follows AM-1 as amended by AM-9: a short transaction commits the PENDING document
(reserving its name), the simulated store write and the finalizing transaction run under
the document's advisory lock, and the version row is inserted only after the store write
succeeded. Any failure leaves the document FAILED (never visible) and no version row. No
transaction is open during the storage call.
"""

import base64
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.config import get_settings
from app.errors import AppError
from app.locks import document_lock
from app.models import AccessLog, Document, DocumentVersion, ProcessingJob, User
from app.schemas import (
    AccessLogOut,
    AccessLogPage,
    CurrentVersionOut,
    DocumentOut,
    DocumentPage,
    ProcessingSummaryOut,
)
from app.services.validation import CONTENT_TYPES, ValidatedFile
from app.storage import build_key
from app.storage.base import ObjectStorage, PutResult
from app.storage.signing import SignedLink, sign_download

logger = logging.getLogger("cloudvault.documents")

STALL_AFTER = timedelta(minutes=10)
VISIBLE_STATUSES = ("ACTIVE", "DELETED")
LISTED_VERSION_STATES = ("ACTIVE", "S3_MISSING")
# `type` filter values: the allowed extensions (doc 05.3) mapped to their content types.
TYPE_FILTERS = {ext.lstrip("."): content_type for ext, content_type in CONTENT_TYPES.items()}
SortKey = Literal["name", "-name", "updated", "-updated", "size", "-size"]


@dataclass(frozen=True)
class UploadResult:
    document: DocumentOut
    duplicate: bool


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _not_found() -> AppError:
    return AppError("NOT_FOUND", 404, "Document not found")


def _name_exists(existing_id: uuid.UUID | None) -> AppError:
    details = {"existing_document_id": str(existing_id)} if existing_id else {}
    return AppError("NAME_EXISTS", 409, "A document with this name already exists", details)


# ---- upload (W2) ----


def _live_document_by_name(db: Session, owner_id: uuid.UUID, name: str) -> Document | None:
    """The PENDING or ACTIVE document holding this name (the partial unique index's scope)."""
    return db.scalar(
        select(Document).where(
            Document.owner_id == owner_id,
            func.lower(Document.display_name) == name.lower(),
            Document.status.in_(("PENDING", "ACTIVE")),
        )
    )


def create_document(
    db: Session, storage: ObjectStorage, owner: User, upload: ValidatedFile, now: datetime | None = None
) -> UploadResult:
    now = now or _utcnow()

    # Duplicate rule (doc 05.3): same name and same content as an ACTIVE document is a no-op.
    existing = _live_document_by_name(db, owner.id, upload.display_name)
    if existing is not None:
        if existing.status == "ACTIVE":
            current = db.get(DocumentVersion, existing.current_version_id)
            if current is not None and current.sha256 == upload.sha256:
                db.commit()
                return UploadResult(document=get_document(db, owner.id, existing.id, now), duplicate=True)
        raise _name_exists(existing.id)

    # Transaction 1: the PENDING document. The partial unique index rejects a concurrent
    # same-name create here, before anything reaches storage (C3).
    doc_id = uuid.uuid4()
    key = build_key(owner.id, doc_id)
    doc = Document(id=doc_id, owner_id=owner.id, display_name=upload.display_name, s3_key=key, status="PENDING")
    try:
        db.add(doc)
        db.flush()
        db.commit()  # also releases the session's connection before the lock is taken
    except IntegrityError as exc:
        db.rollback()
        conflict = _live_document_by_name(db, owner.id, upload.display_name)
        db.rollback()
        raise _name_exists(conflict.id if conflict else None) from exc

    with document_lock(doc_id):
        try:
            stored = store_upload(storage, key, doc_id, owner.id, upload)
        except BaseException:
            _mark_failed(db, doc_id)
            raise

        try:
            _finalize(db, doc_id, upload, stored.version_id)
        except BaseException:
            # The object exists but the application never adopted it: remove that exact
            # version (best effort; reconcile finds leftovers) and mark the document FAILED.
            db.rollback()
            discard_stored_version(storage, key, stored.version_id)
            _mark_failed(db, doc_id)
            raise

    return UploadResult(document=get_document(db, owner.id, doc_id, now), duplicate=False)


def store_upload(
    storage: ObjectStorage, key: str, doc_id: uuid.UUID, owner_id: uuid.UUID, upload: ValidatedFile
) -> PutResult:
    """PutObject with CloudVault's metadata, tags and SHA-256 checksum (doc 02.2). Shared with T11."""
    return storage.put_object(
        key,
        upload.data,
        content_type=upload.content_type,
        metadata={"cv-doc-id": str(doc_id), "cv-owner-id": str(owner_id)},
        tags={"project": "cloudvault", "env": get_settings().app_env},
        checksum_sha256=base64.b64encode(bytes.fromhex(upload.sha256)).decode("ascii"),
    )


def _finalize(db: Session, doc_id: uuid.UUID, upload: ValidatedFile, store_version_id: str) -> None:
    """Transaction 2: insert v1 with the store's version id; the document becomes ACTIVE with its PENDING job."""
    doc = db.get(Document, doc_id, with_for_update=True, populate_existing=True)
    version = DocumentVersion(
        document_id=doc_id,
        version_number=1,
        s3_version_id=store_version_id,
        size_bytes=upload.size_bytes,
        content_type=upload.content_type,
        sha256=upload.sha256,
        origin="UPLOAD",
        state="ACTIVE",
    )
    db.add(version)
    db.flush()
    doc.status = "ACTIVE"
    doc.current_version_id = version.id
    db.add(ProcessingJob(version_id=version.id, document_id=doc_id))
    db.commit()


def _mark_failed(db: Session, doc_id: uuid.UUID) -> None:
    """Best effort: the PENDING document becomes FAILED. Errors are logged; the caller re-raises the original."""
    try:
        db.rollback()
        db.execute(
            update(Document).where(Document.id == doc_id, Document.status == "PENDING").values(status="FAILED")
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not mark upload %s as FAILED; reconcile will handle it", doc_id)


def discard_stored_version(storage: ObjectStorage, key: str, version_id: str) -> None:
    try:
        storage.delete_version(key, version_id)
    except Exception:
        logger.exception("Could not delete unadopted stored version of %s; reconcile will handle it", key)


# ---- reads ----


def _visible_documents_query(owner_id: uuid.UUID) -> tuple[Select, type[DocumentVersion], type[ProcessingJob]]:
    current = aliased(DocumentVersion, name="current_version")
    job = aliased(ProcessingJob, name="current_job")
    version_count = (
        select(func.count(DocumentVersion.id))
        .where(DocumentVersion.document_id == Document.id, DocumentVersion.state.in_(LISTED_VERSION_STATES))
        .correlate(Document)
        .scalar_subquery()
    )
    query = (
        select(Document, current, job, version_count.label("version_count"))
        .join(current, current.id == Document.current_version_id)
        .outerjoin(job, job.version_id == current.id)
        .where(Document.owner_id == owner_id, Document.status.in_(VISIBLE_STATUSES))
    )
    return query, current, job


def _to_out(
    doc: Document, current: DocumentVersion, job: ProcessingJob | None, version_count: int, now: datetime
) -> DocumentOut:
    processing = None
    if job is not None:
        processing = ProcessingSummaryOut(
            status=job.status,
            page_count=job.page_count,
            word_count=job.word_count,
            stalled=job.status == "PENDING" and job.created_at < now - STALL_AFTER,
        )
    return DocumentOut(
        id=doc.id,
        display_name=doc.display_name,
        status=doc.status,
        current_version=CurrentVersionOut(
            version_number=current.version_number,
            size_bytes=current.size_bytes,
            content_type=current.content_type,
            storage_class=current.storage_class,
            created_at=current.created_at,
            origin=current.origin,
            state=current.state,
        ),
        version_count=version_count,
        processing=processing,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        deleted_at=doc.deleted_at,
    )


def get_document(db: Session, owner_id: uuid.UUID, document_id: uuid.UUID, now: datetime | None = None) -> DocumentOut:
    """Owner-scoped detail; other users' and PENDING/FAILED documents are 404 (doc 05.1)."""
    query, _, _ = _visible_documents_query(owner_id)
    row = db.execute(query.where(Document.id == document_id)).first()
    db.commit()
    if row is None:
        raise _not_found()
    return _to_out(*row, now or _utcnow())


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_documents(
    db: Session,
    owner_id: uuid.UUID,
    *,
    q: str | None = None,
    status: Literal["active", "deleted"] = "active",
    type_: str | None = None,
    storage_class: str | None = None,
    sort: SortKey = "-updated",
    page: int = 1,
    page_size: int = 25,
    now: datetime | None = None,
) -> DocumentPage:
    """W7: search, filter, sort and paginate the owner's documents (doc 05.5)."""
    query, current, job = _visible_documents_query(owner_id)
    query = query.where(Document.status == status.upper())
    if q:
        pattern = f"%{_escape_like(q)}%"
        query = query.where(
            or_(Document.display_name.ilike(pattern, escape="\\"), job.text_excerpt.ilike(pattern, escape="\\"))
        )
    if type_:
        query = query.where(current.content_type == TYPE_FILTERS[type_])
    if storage_class:
        query = query.where(current.storage_class == storage_class)

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    column = {
        "name": func.lower(Document.display_name),
        "updated": Document.updated_at,
        "size": current.size_bytes,
    }[sort.lstrip("-")]
    order = column.desc() if sort.startswith("-") else column.asc()
    rows = db.execute(query.order_by(order, Document.id).offset((page - 1) * page_size).limit(page_size)).all()
    db.commit()
    now = now or _utcnow()
    return DocumentPage(
        items=[_to_out(*row, now) for row in rows], total=total or 0, page=page, page_size=page_size
    )


# ---- download (W3) and access log (W9) ----


def _owned_visible_document(db: Session, owner_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.owner_id == owner_id, Document.status.in_(VISIBLE_STATUSES)
        )
    )
    if doc is None:
        raise _not_found()
    return doc


def _listed_version(db: Session, doc: Document, version_number: int | None) -> DocumentVersion:
    """The current version, or version `n`; only ACTIVE and S3_MISSING versions exist for callers."""
    if version_number is None:
        version = db.get(DocumentVersion, doc.current_version_id)
    else:
        version = db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == doc.id,
                DocumentVersion.version_number == version_number,
                DocumentVersion.state.in_(LISTED_VERSION_STATES),
            )
        )
    if version is None:
        raise AppError("VERSION_NOT_FOUND", 404, "Version not found")
    return version


def create_download_link(
    db: Session,
    owner_id: uuid.UUID,
    document_id: uuid.UUID,
    version_number: int | None,
    *,
    bucket: str,
    now_epoch: int,
) -> SignedLink:
    """W3: owner + ACTIVE checks, sign locally (no storage call, AM-4), log, then return.

    The access-log row is committed before the link is returned; if that fails, no link is
    issued (fail closed, doc 03 W3).
    """
    settings = get_settings()
    doc = _owned_visible_document(db, owner_id, document_id)
    if doc.status == "DELETED":
        raise AppError("DOCUMENT_DELETED", 409, "Document is in the trash")
    version = _listed_version(db, doc, version_number)
    if version.state == "S3_MISSING":
        raise AppError("VERSION_EXPIRED", 410, "This version is no longer in storage")
    link = sign_download(
        secret=settings.sim_signing_secret,
        base_url=settings.public_api_base_url,
        bucket=bucket,
        key=doc.s3_key,
        version_id=version.s3_version_id,
        filename=doc.display_name,
        now=now_epoch,
        ttl_seconds=settings.presign_expiry_seconds,
    )
    record_access(db, doc, version, owner_id)
    return link


def record_access(db: Session, doc: Document, version: DocumentVersion, user_id: uuid.UUID) -> None:
    """[APP] Access is recorded when CloudVault issues the link; S3 does not report downloads back (W9)."""
    db.add(AccessLog(document_id=doc.id, version_id=version.id, user_id=user_id, event_type="DOWNLOAD"))
    db.commit()


def list_access_logs(
    db: Session, owner_id: uuid.UUID, document_id: uuid.UUID, page: int = 1, page_size: int = 25
) -> AccessLogPage:
    """Newest first; available for trashed documents too (history stays visible)."""
    doc = _owned_visible_document(db, owner_id, document_id)
    total = db.scalar(select(func.count(AccessLog.id)).where(AccessLog.document_id == doc.id)) or 0
    rows = db.execute(
        select(AccessLog.accessed_at, DocumentVersion.version_number, AccessLog.event_type)
        .join(DocumentVersion, DocumentVersion.id == AccessLog.version_id)
        .where(AccessLog.document_id == doc.id)
        .order_by(AccessLog.accessed_at.desc(), AccessLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    db.commit()
    return AccessLogPage(
        items=[AccessLogOut(accessed_at=a, version_number=n, event_type=e) for a, n, e in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
