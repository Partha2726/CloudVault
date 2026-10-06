"""Version list, new version (W5) and restore (W6) (doc 03, 05.5; AM-1, AM-2, AM-7).

Same pattern as T8/T10: the request session commits before the document lock is taken;
under the lock, any leftover `pending_op` is recovered first (shared with T10), then:

1. Check transaction (row-locked): check state and inputs; nothing is written; commit.
2. Store call (PutObject or CopyObject) with no transaction open.
3. Finalize transaction: allocate `version_number = max + 1`, insert the version row as
   ACTIVE with the store's version id, make it the document's current version and insert
   its new PENDING processing job; commit. A version row therefore never exists without
   a store version id (AM-9).

Because the store write and the finalize happen inside the same document lock,
concurrent writers to one document run one after another: version numbers are n, n+1,
... and the store creates versions in the same order, so the store's latest version is
always the DB's current version. Different documents use different locks.

Failures: a failed store call writes nothing; a failed finalize removes the stored version
it just created (it is the store's latest, under the lock, so removing it restores the
previous current) and writes nothing. Version numbers have no gaps.
"""

import logging
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.locks import document_lock
from app.models import Document, DocumentVersion, ProcessingJob, User
from app.schemas import S3InfoOut, VersionList, VersionOut
from app.services.deletion_service import recover_interrupted
from app.services.document_service import (
    LISTED_VERSION_STATES,
    VISIBLE_STATUSES,
    discard_stored_version,
    store_upload,
)
from app.services.validation import ValidatedFile
from app.storage.base import STANDARD, MethodNotAllowed, NoSuchVersion, ObjectStorage

logger = logging.getLogger("cloudvault.versions")


def _not_found() -> AppError:
    return AppError("NOT_FOUND", 404, "Document not found")


def _deleted() -> AppError:
    return AppError("DOCUMENT_DELETED", 409, "Document is in the trash")


def _version_not_found() -> AppError:
    return AppError("VERSION_NOT_FOUND", 404, "Version not found")


def _version_expired() -> AppError:
    return AppError("VERSION_EXPIRED", 410, "This version is no longer in storage")


def to_version_out(version: DocumentVersion, current_version_id: uuid.UUID | None) -> VersionOut:
    return VersionOut(
        version_number=version.version_number,
        size_bytes=version.size_bytes,
        content_type=version.content_type,
        sha256=version.sha256,
        storage_class=version.storage_class,
        origin=version.origin,
        restored_from_version=version.restored_from_version,
        state=version.state,
        is_current=version.id == current_version_id,
        created_at=version.created_at,
    )


# ---- reads ----


def list_versions(db: Session, owner_id: uuid.UUID, document_id: uuid.UUID) -> VersionList:
    """Newest first; ACTIVE and S3_MISSING versions only (PENDING/FAILED never shown)."""
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.owner_id == owner_id, Document.status.in_(VISIBLE_STATUSES)
        )
    )
    if doc is None:
        db.rollback()
        raise _not_found()
    versions = db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == doc.id, DocumentVersion.state.in_(LISTED_VERSION_STATES))
        .order_by(DocumentVersion.version_number.desc())
    ).all()
    db.commit()
    return VersionList(items=[to_version_out(v, doc.current_version_id) for v in versions])


# ---- transaction helpers (each is one short transaction) ----


def _load_active(db: Session, owner_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    doc = db.scalar(
        select(Document)
        .where(Document.id == document_id, Document.owner_id == owner_id, Document.status.in_(VISIBLE_STATUSES))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if doc is None:
        db.rollback()
        raise _not_found()
    if doc.status != "ACTIVE":
        db.rollback()
        raise _deleted()
    return doc


def _next_version_number(db: Session, document_id: uuid.UUID) -> int:
    """max + 1 over the document's version rows. Call under the lock."""
    current_max = db.scalar(
        select(func.max(DocumentVersion.version_number)).where(DocumentVersion.document_id == document_id)
    )
    return (current_max or 0) + 1


def _finalize(db: Session, document_id: uuid.UUID, store_version_id: str, **fields) -> uuid.UUID:
    """Finalize transaction: insert the ACTIVE version with its store id, make it current and
    add its new PENDING job (old jobs are never touched), committed together or not at all."""
    try:
        doc = db.get(Document, document_id, with_for_update=True, populate_existing=True)
        version = DocumentVersion(
            document_id=document_id,
            version_number=_next_version_number(db, document_id),
            s3_version_id=store_version_id,
            state="ACTIVE",
            **fields,
        )
        db.add(version)
        db.flush()
        doc.current_version_id = version.id
        db.add(ProcessingJob(version_id=version.id, document_id=document_id))
        db.commit()
        return version.id
    except BaseException:
        db.rollback()
        raise


def _version_out(db: Session, document_id: uuid.UUID, version_id: uuid.UUID) -> VersionOut:
    version = db.get(DocumentVersion, version_id, populate_existing=True)
    doc = db.get(Document, document_id, populate_existing=True)
    out = to_version_out(version, doc.current_version_id)
    db.commit()
    return out


def _enter(db: Session, storage: ObjectStorage, owner_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    """Under the lock: recover an interrupted operation, then require an ACTIVE document."""
    doc, _ = recover_interrupted(db, storage, owner_id, document_id)
    if doc.status != "ACTIVE":  # includes a trashed document with an unfinished purge
        raise _deleted()
    return doc


# ---- W5: new version ----


def upload_version(
    db: Session, storage: ObjectStorage, owner: User, document_id: uuid.UUID, upload: ValidatedFile
) -> VersionOut | None:
    """Returns the new version, or None when the content equals the current version (duplicate)."""
    db.commit()  # the request session holds no connection while waiting for the lock
    with document_lock(document_id):
        _enter(db, storage, owner.id, document_id)

        doc = _load_active(db, owner.id, document_id)
        current = db.get(DocumentVersion, doc.current_version_id)
        if current is not None and current.sha256 == upload.sha256:
            db.commit()
            return None
        key, doc_id = doc.s3_key, doc.id
        db.commit()  # check transaction: nothing written

        stored = store_upload(storage, key, doc_id, owner.id, upload)
        try:
            version_id = _finalize(
                db, doc_id, stored.version_id,
                size_bytes=upload.size_bytes, content_type=upload.content_type, sha256=upload.sha256,
                origin="UPLOAD",
            )
        except BaseException:
            discard_stored_version(storage, key, stored.version_id)
            raise
    return _version_out(db, document_id, version_id)


# ---- W6: restore ----


def restore_version(
    db: Session, storage: ObjectStorage, owner: User, document_id: uuid.UUID, version_number: int
) -> VersionOut:
    """CopyObject from version n onto the same key: a NEW current version (AM-2).

    No storage class is passed to the copy, so the restored version is STANDARD whatever
    the source class was (docs/VERIFIED.md row 4). The new version gets its own PENDING
    processing job; the source version's job is left as history. Not idempotent.
    """
    db.commit()
    with document_lock(document_id):
        _enter(db, storage, owner.id, document_id)

        doc = _load_active(db, owner.id, document_id)
        source = db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == doc.id,
                DocumentVersion.version_number == version_number,
                DocumentVersion.state.in_(LISTED_VERSION_STATES),
            )
        )
        if source is None:
            db.rollback()
            raise _version_not_found()
        if source.state == "S3_MISSING":
            db.rollback()
            raise _version_expired()
        fields = dict(
            size_bytes=source.size_bytes,
            content_type=source.content_type,
            sha256=source.sha256,
            storage_class=STANDARD,
            origin="RESTORE",
            restored_from_version=source.version_number,
        )
        key, doc_id, source_id, source_store_id = doc.s3_key, doc.id, source.id, source.s3_version_id
        db.commit()  # check transaction: nothing written

        try:
            stored = storage.copy_object(key, source_store_id)  # no class: STANDARD
        except (NoSuchVersion, MethodNotAllowed) as exc:
            # The store no longer holds the source version: record it, never recreate data.
            _mark_source_missing(db, source_id)
            raise _version_expired() from exc
        try:
            version_id = _finalize(db, doc_id, stored.version_id, **fields)
        except BaseException:
            discard_stored_version(storage, key, stored.version_id)
            raise
    return _version_out(db, document_id, version_id)


def _mark_source_missing(db: Session, version_id: uuid.UUID) -> None:
    try:
        db.rollback()
        db.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == version_id, DocumentVersion.state == "ACTIVE")
            .values(state="S3_MISSING")
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not mark version %s S3_MISSING; reconcile will handle it", version_id)


# ---- S3 Inspector (T12) ----


def s3_info(
    db: Session, storage: ObjectStorage, owner_id: uuid.UUID, document_id: uuid.UUID, version_number: int | None
) -> S3InfoOut:
    """[S3-SIM] HeadObject + GetObjectTagging for one version (W8); never reads the bytes.

    Trashed documents can be inspected (doc 05.5 lists no 409): HEAD with a version id
    works even when a delete marker is the current entry. A version the store no longer
    holds is marked S3_MISSING and answered with 410 VERSION_EXPIRED.
    """
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.owner_id == owner_id, Document.status.in_(VISIBLE_STATUSES)
        )
    )
    if doc is None:
        db.rollback()
        raise _not_found()
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
    key = doc.s3_key
    db.commit()  # no transaction open during the storage calls
    if version is None:
        raise _version_not_found()
    if version.state == "S3_MISSING":
        raise _version_expired()

    try:
        head = storage.head_object(key, version.s3_version_id)
        tags = storage.get_object_tagging(key, version.s3_version_id)
    except NoSuchVersion as exc:
        _mark_source_missing(db, version.id)
        raise _version_expired() from exc
    except MethodNotAllowed as exc:  # the recorded id names a delete marker: inconsistent store
        raise AppError("STORAGE_ERROR", 502, "Stored version is a delete marker") from exc
    return S3InfoOut(
        bucket=head.bucket,
        key=head.key,
        version_id=head.version_id,
        etag=head.etag,
        content_length=head.size_bytes,
        content_type=head.content_type,
        last_modified=head.last_modified,
        storage_class=head.storage_class or STANDARD,  # HEAD omits the class for STANDARD
        metadata=head.metadata,
        tags=tags,
    )
