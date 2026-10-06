"""Apply's final DB step and recovery of an interrupted Apply (`pending_op='APPLY'`) (T14).

Apply (doc 03 W11, AM-1) runs under the document lock:

  1. txn: re-check, record `pending_op='APPLY'` (`pending_op_at` = t0)
  2. store: CopyObject(current version, target class)            -> new stored version
  3. txn: version row -> new store id + class; recommendation APPLIED  (pending_op kept)
  4. store: delete the old stored version (best effort)
  5. txn: clear pending_op

A crash can stop it after any step. Recovery runs at the start of the next operation on
the document (holding the lock, so the interrupted Apply cannot still be running) and is
decided only from persisted state:

  A. after 1, before 2: the store has no new copy        -> drop the intent; the
     recommendation stays OPEN.
  B. after 2, before 3: the store's latest entry is the copy, not yet adopted
     -> roll forward: do step 3 with that copy, then 4 and 5.
  C. after 3, before 4: the old version is still stored but unreferenced
     -> do steps 4 and 5.
  D. after 4, before 5: nothing left to clean               -> do step 5.

The copy of step 2 is recognised strictly: it must be the latest stored entry for the key,
referenced by no version row, not a delete marker, have the current version's ETag (a copy
keeps the bytes), have the open recommendation's target class, and be written at or after
`pending_op_at`. Anything else (for example a stray object from an earlier failed write)
is never adopted. Cleanup deletes only stored versions that no version row references, are
not delete markers, carry the current version's ETag and are older than the current
stored version, so a version the application points at is never deleted.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Document, DocumentVersion, StorageRecommendation
from app.storage.base import ObjectStorage

logger = logging.getLogger("cloudvault.apply")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def finalize_apply(
    db: Session,
    version_id: uuid.UUID,
    recommendation_id: uuid.UUID | None,
    new_store_version_id: str,
    new_class: str,
) -> None:
    """Step 3: the version row points at the new stored copy; the recommendation is APPLIED.

    The version keeps its number and row (owner decision 2026-10-04), so its access
    history carries over. `pending_op` stays set until the old version is cleaned up.
    """
    now = _utcnow()
    try:
        version = db.get(DocumentVersion, version_id, with_for_update=True, populate_existing=True)
        version.s3_version_id = new_store_version_id
        version.storage_class = new_class
        version.storage_class_changed_at = now
        if recommendation_id is not None:
            rec = db.get(StorageRecommendation, recommendation_id, with_for_update=True, populate_existing=True)
            if rec is not None and rec.status == "OPEN":
                rec.status, rec.resolved_at = "APPLIED", now
        db.commit()
    except BaseException:
        db.rollback()
        raise


def clear_apply_intent(db: Session, document_id: uuid.UUID) -> None:
    """Step 5. Only clears an APPLY intent, never another operation's."""
    try:
        doc = db.get(Document, document_id, with_for_update=True, populate_existing=True)
        if doc is not None and doc.pending_op == "APPLY":
            doc.pending_op, doc.pending_op_at = None, None
        db.commit()
    except BaseException:
        db.rollback()
        raise


def remove_unreferenced_copies(db: Session, storage: ObjectStorage, doc: Document) -> int:
    """Step 4 (and recovery C): delete stored versions of the current content that nothing references."""
    current = db.get(DocumentVersion, doc.current_version_id, populate_existing=True)
    referenced = {
        v for v in db.scalars(select(DocumentVersion.s3_version_id).where(DocumentVersion.document_id == doc.id))
        if v
    }
    db.commit()
    entries = [e for e in storage.list_object_versions(doc.s3_key) if e.key == doc.s3_key]
    position = next((i for i, e in enumerate(entries) if e.version_id == current.s3_version_id), None)
    if position is None:
        return 0
    current_etag = entries[position].etag
    removed = 0
    for entry in entries[position + 1:]:  # older than the current stored version
        if not entry.is_delete_marker and entry.version_id not in referenced and entry.etag == current_etag:
            storage.delete_version(doc.s3_key, entry.version_id)
            removed += 1
    return removed


def recover_apply(db: Session, storage: ObjectStorage, doc: Document) -> bool:
    """Resolve `pending_op='APPLY'` (states A-D above). Returns True if a copy was adopted (B).

    Call while holding the document lock, with no transaction open.
    """
    current = db.get(DocumentVersion, doc.current_version_id, populate_existing=True)
    referenced = {
        v for v in db.scalars(select(DocumentVersion.s3_version_id).where(DocumentVersion.document_id == doc.id))
        if v
    }
    rec = db.scalar(
        select(StorageRecommendation).where(
            StorageRecommendation.version_id == current.id, StorageRecommendation.status == "OPEN"
        )
    ) if current is not None else None
    rec_id, rec_target = (rec.id, rec.recommended_class) if rec else (None, None)
    pending_since = doc.pending_op_at
    db.commit()

    adopted = False
    if current is not None and current.s3_version_id:
        entries = [e for e in storage.list_object_versions(doc.s3_key) if e.key == doc.s3_key]
        current_entry = next((e for e in entries if e.version_id == current.s3_version_id), None)
        latest = entries[0] if entries else None
        if (
            latest is not None
            and current_entry is not None
            and latest.version_id not in referenced
            and not latest.is_delete_marker
            and latest.etag == current_entry.etag
            and rec_target is not None
            and latest.storage_class == rec_target
            and pending_since is not None
            and latest.last_modified >= pending_since
        ):
            finalize_apply(db, current.id, rec_id, latest.version_id, latest.storage_class)  # state B
            adopted = True
            logger.info("Recovered interrupted Apply on %s: adopted %s", doc.id, latest.version_id)

    try:
        removed = remove_unreferenced_copies(db, storage, doc)  # states B and C
    except Exception as exc:
        db.rollback()
        raise AppError("STORAGE_ERROR", 502, "Could not finish an earlier storage-class change") from exc
    if removed:
        logger.info("Recovered interrupted Apply on %s: removed %d old stored version(s)", doc.id, removed)
    clear_apply_intent(db, doc.id)  # states A-D
    return adopted
