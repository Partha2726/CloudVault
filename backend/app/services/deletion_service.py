"""Soft delete, undelete and permanent delete (doc 02.5, doc 03 W4, doc 05.5; AM-1, AM-4).

Pattern (same as T8): the request session holds no connection when the document lock is
taken; under the lock, short transactions record intent (`pending_op`), the simulated
store call runs with no transaction open, and a final short transaction records the
result.

Recovery: the document lock is a session advisory lock, so it is released when a process
dies. A `pending_op` seen while holding the lock therefore belongs to an interrupted
operation, never a live one. It is resolved first, from the store's actual state, so a
retry can never add a second delete marker or undo a half-finished permanent delete.

Failure strategy:
- Store call fails: clear `pending_op`, nothing changed, report the error.
- Final transaction fails after the store call: leave `pending_op` set; the next operation
  on the document (or `reconcile`) rolls it forward, because the store already holds the
  new state.
- Undelete hits the name index (a same-name document appeared meanwhile): roll back by
  adding a new delete marker, record its id, answer 409 NAME_EXISTS.
- Permanent delete: rows are removed only after the store holds no version or marker for
  the key; on any failure the document stays DELETED with `pending_op='PURGE'`, undelete
  is refused, and repeating the permanent delete resumes the cleanup.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.locks import document_lock
from app.models import Document
from app.schemas import DocumentOut
from app.services.apply_recovery import recover_apply
from app.services.document_service import VISIBLE_STATUSES, get_document
from app.storage.base import MethodNotAllowed, NoSuchVersion, ObjectStorage

logger = logging.getLogger("cloudvault.deletion")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _not_found() -> AppError:
    return AppError("NOT_FOUND", 404, "Document not found")


def _storage_error(message: str) -> AppError:
    return AppError("STORAGE_ERROR", 502, message)


def _purge_in_progress() -> AppError:
    return AppError(
        "DOCUMENT_DELETED", 409, "Permanent deletion of this document is in progress; repeat the permanent delete"
    )


# ---- small transactions ----


def _load(db: Session, owner_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    """Fresh, row-locked read of a visible document inside a new short transaction."""
    doc = db.scalar(
        select(Document)
        .where(Document.id == document_id, Document.owner_id == owner_id, Document.status.in_(VISIBLE_STATUSES))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if doc is None:
        db.rollback()
        raise _not_found()
    return doc


def _snapshot(db: Session, owner_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    doc = _load(db, owner_id, document_id)
    db.commit()  # no transaction stays open while the store is called
    return doc


def _set_pending(db: Session, owner_id: uuid.UUID, document_id: uuid.UUID, op: str) -> Document:
    doc = _load(db, owner_id, document_id)
    doc.pending_op, doc.pending_op_at = op, _utcnow()
    db.commit()
    return doc


def _clear_pending(db: Session, document_id: uuid.UUID) -> None:
    """Best effort; a leftover marker is resolved by the next operation or reconcile."""
    try:
        db.rollback()
        doc = db.get(Document, document_id, with_for_update=True, populate_existing=True)
        if doc is not None:
            doc.pending_op, doc.pending_op_at = None, None
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not clear pending_op on %s; it will be recovered later", document_id)


def _finish_soft_delete(db: Session, owner_id: uuid.UUID, document_id: uuid.UUID, marker_id: str) -> None:
    doc = _load(db, owner_id, document_id)
    doc.status, doc.deleted_at, doc.delete_marker_version_id = "DELETED", _utcnow(), marker_id
    doc.pending_op, doc.pending_op_at = None, None
    db.commit()


def _finish_undelete(db: Session, owner_id: uuid.UUID, document_id: uuid.UUID) -> None:
    doc = _load(db, owner_id, document_id)
    doc.status, doc.deleted_at, doc.delete_marker_version_id = "ACTIVE", None, None
    doc.pending_op, doc.pending_op_at = None, None
    db.commit()


def _delete_rows(db: Session, document_id: uuid.UUID) -> None:
    """Remove the document; versions, jobs, access logs and recommendations cascade (doc 04)."""
    db.rollback()
    db.execute(delete(Document).where(Document.id == document_id))
    db.commit()


def _name_holder(db: Session, doc: Document) -> uuid.UUID | None:
    holder = db.scalar(
        select(Document.id).where(
            Document.owner_id == doc.owner_id,
            Document.id != doc.id,
            func.lower(Document.display_name) == doc.display_name.lower(),
            Document.status.in_(("PENDING", "ACTIVE")),
        )
    )
    db.commit()
    return holder


def _name_exists(holder: uuid.UUID | None) -> AppError:
    details = {"existing_document_id": str(holder)} if holder else {}
    return AppError("NAME_EXISTS", 409, "An active document with this name exists", details)


# ---- store inspection ----


def _latest_store_entry(storage: ObjectStorage, key: str):
    entries = [e for e in storage.list_object_versions(key) if e.key == key]
    return entries[0] if entries else None


def _store_has_version(storage: ObjectStorage, key: str, version_id: str) -> bool:
    try:
        storage.head_object(key, version_id)
    except NoSuchVersion:
        return False
    except MethodNotAllowed:  # the version exists and is a delete marker
        return True
    return True


# ---- recovery of interrupted operations ----


def recover_interrupted(
    db: Session, storage: ObjectStorage, owner_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[Document, str | None]:
    """Resolve a leftover pending_op (call while holding the document lock).

    Returns the fresh document and the operation completed, if any. Shared with T11 and T14.
    """
    doc = _snapshot(db, owner_id, document_id)
    op = doc.pending_op
    if op is None or op == "PURGE":  # PURGE stays until a permanent delete finishes it
        return doc, None

    if op == "DELETE":
        latest = _latest_store_entry(storage, doc.s3_key)
        if doc.status == "ACTIVE" and latest is not None and latest.is_delete_marker:
            _finish_soft_delete(db, owner_id, document_id, latest.version_id)
            logger.info("Recovered interrupted soft delete of %s", document_id)
            return _snapshot(db, owner_id, document_id), "DELETE"
    elif op == "UNDELETE":
        marker = doc.delete_marker_version_id
        if doc.status == "DELETED" and marker and not _store_has_version(storage, doc.s3_key, marker):
            try:
                _finish_undelete(db, owner_id, document_id)
            except IntegrityError:
                db.rollback()
                _restore_marker(db, storage, owner_id, document_id, doc.s3_key)
                return _snapshot(db, owner_id, document_id), None
            logger.info("Recovered interrupted undelete of %s", document_id)
            return _snapshot(db, owner_id, document_id), "UNDELETE"
    elif op == "APPLY":  # T14: deterministic roll-forward/cleanup, see app/services/apply_recovery.py
        adopted = recover_apply(db, storage, doc)
        return _snapshot(db, owner_id, document_id), "APPLY" if adopted else None

    _clear_pending(db, document_id)  # the store never changed: just drop the stale intent
    return _snapshot(db, owner_id, document_id), None


def _restore_marker(db: Session, storage: ObjectStorage, owner_id: uuid.UUID, document_id: uuid.UUID, key: str):
    """Undo an undelete in the store: add a fresh delete marker and record it (doc stays DELETED)."""
    marker_id = storage.delete_object(key)
    doc = _load(db, owner_id, document_id)
    doc.delete_marker_version_id = marker_id
    doc.pending_op, doc.pending_op_at = None, None
    db.commit()


# ---- operations ----


def soft_delete(db: Session, storage: ObjectStorage, owner_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """W4: plain DeleteObject adds a delete marker; idempotent (204 when already in trash)."""
    db.commit()  # release the request session's connection before waiting for the lock
    with document_lock(document_id):
        doc, _ = recover_interrupted(db, storage, owner_id, document_id)
        if doc.status == "DELETED":
            return
        doc = _set_pending(db, owner_id, document_id, "DELETE")
        try:
            marker_id = storage.delete_object(doc.s3_key)
        except BaseException:
            _clear_pending(db, document_id)
            raise
        # A failure here leaves pending_op='DELETE'; recovery finds the marker and finishes.
        _finish_soft_delete(db, owner_id, document_id, marker_id)


def undelete(db: Session, storage: ObjectStorage, owner_id: uuid.UUID, document_id: uuid.UUID) -> DocumentOut:
    """Remove the stored delete marker by its version id; the previous version is current again."""
    db.commit()
    with document_lock(document_id):
        doc, completed = recover_interrupted(db, storage, owner_id, document_id)
        if completed == "UNDELETE":  # an earlier attempt already finished in the store
            return get_document(db, owner_id, document_id)
        if doc.pending_op == "PURGE":
            raise _purge_in_progress()
        if doc.status != "DELETED":
            raise AppError("NOT_DELETED", 409, "Document is not in the trash")
        holder = _name_holder(db, doc)
        if holder is not None:
            raise _name_exists(holder)

        doc = _set_pending(db, owner_id, document_id, "UNDELETE")
        try:
            storage.delete_version(doc.s3_key, doc.delete_marker_version_id)
        except BaseException:
            _clear_pending(db, document_id)
            raise
        try:
            _finish_undelete(db, owner_id, document_id)
        except IntegrityError as exc:
            # A same-name document was created after the check: put the object back in the trash.
            db.rollback()
            _restore_marker(db, storage, owner_id, document_id, doc.s3_key)
            raise _name_exists(_name_holder(db, doc)) from exc
        # Any other failure leaves pending_op='UNDELETE'; recovery finishes it (marker is gone).
    return get_document(db, owner_id, document_id)


def permanent_delete(db: Session, storage: ObjectStorage, owner_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """Delete every stored version and marker, then the rows. Only for documents in the trash."""
    db.commit()
    with document_lock(document_id):
        doc, _ = recover_interrupted(db, storage, owner_id, document_id)
        if doc.status != "DELETED":
            raise AppError("NOT_DELETED", 409, "Only documents in the trash can be permanently deleted")
        doc = _set_pending(db, owner_id, document_id, "PURGE")

        # From here on, any failure keeps the document DELETED with pending_op='PURGE'.
        results = storage.delete_all_versions(doc.s3_key)
        failed = [r.version_id for r in results if not r.deleted]
        if failed:
            logger.warning("Permanent delete of %s left %d stored versions", document_id, len(failed))
            raise _storage_error("Some stored versions could not be deleted; repeat the permanent delete")
        if _latest_store_entry(storage, doc.s3_key) is not None:
            raise _storage_error("Stored versions remain; repeat the permanent delete")
        _delete_rows(db, document_id)

