"""Storage recommendations: refresh, list, dismiss, apply (doc 03 W10/W11, doc 07; AM-1, AM-7).

[APP] Recommendations are CloudVault's heuristic (T13 engine), not AWS Intelligent-Tiering.
Calculation (`evaluate_version`) is pure and separate from mutation (`apply`).

Recommendation states: OPEN -> APPLIED | DISMISSED | STALE (all final).
- refresh: every OPEN recommendation of the user's evaluated documents becomes STALE and a
  new OPEN one is inserted for each current RECOMMEND result.
- apply: OPEN -> APPLIED (or STALE when the engine result changed: 409).
- dismiss: OPEN -> DISMISSED; repeating it changes nothing.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.locks import document_lock
from app.models import AccessLog, Document, DocumentVersion, StorageRecommendation
from app.schemas import RecommendationList, RecommendationOut
from app.services.apply_recovery import clear_apply_intent, finalize_apply
from app.services.deletion_service import recover_interrupted
from app.services.document_service import VISIBLE_STATUSES
from app.services.recommendation_engine import EngineConfig, Result, VersionInputs, evaluate
from app.storage.base import MethodNotAllowed, NoSuchVersion, ObjectStorage

logger = logging.getLogger("cloudvault.recommendations")

RecStatus = Literal["open", "applied", "dismissed", "stale"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _not_found() -> AppError:
    return AppError("NOT_FOUND", 404, "Recommendation not found")


def _stale(message: str = "The recommendation no longer matches the document; refresh recommendations") -> AppError:
    return AppError("STALE_RECOMMENDATION", 409, message)


# ---- calculation (no mutation) ----


def load_inputs(db: Session, version: DocumentVersion, now: datetime) -> VersionInputs:
    """Doc 07.1 inputs; access counts come from CloudVault's own access log."""
    since_30, since_90 = now - timedelta(days=30), now - timedelta(days=90)
    a30, a90, last = db.execute(
        select(
            func.count(AccessLog.id).filter(AccessLog.accessed_at >= since_30),
            func.count(AccessLog.id).filter(AccessLog.accessed_at >= since_90),
            func.max(AccessLog.accessed_at),
        ).where(AccessLog.version_id == version.id)
    ).one()
    return VersionInputs(
        size_bytes=version.size_bytes,
        storage_class=version.storage_class,
        created_at=version.created_at,
        storage_class_changed_at=version.storage_class_changed_at,
        a30=a30,
        a90=a90,
        last_access=last,
    )


def evaluate_version(db: Session, version: DocumentVersion, now: datetime) -> Result:
    return evaluate(load_inputs(db, version, now), now, EngineConfig.from_settings(get_settings()))


def _matches(rec: StorageRecommendation, result: Result) -> bool:
    return result.is_recommendation and result.rule_id == rec.rule_id and result.target == rec.recommended_class


# ---- shapes ----


def _query_for_owner(owner_id: uuid.UUID):
    return (
        select(StorageRecommendation, Document, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.id == StorageRecommendation.version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.owner_id == owner_id, Document.status.in_(VISIBLE_STATUSES))
    )


def _to_out(rec: StorageRecommendation, doc: Document, version: DocumentVersion) -> RecommendationOut:
    return RecommendationOut(
        id=rec.id,
        document_id=doc.id,
        display_name=doc.display_name,
        version_number=version.version_number,
        current_class=rec.current_class,
        recommended_class=rec.recommended_class,
        rule_id=rec.rule_id,
        reason=rec.reason,
        signals=rec.signals,
        estimate=None,  # doc 07.5: only with a pricing file; no estimate format is specified yet
        status=rec.status,
        created_at=rec.created_at,
    )


def _get_out(db: Session, owner_id: uuid.UUID, recommendation_id: uuid.UUID) -> RecommendationOut:
    row = db.execute(
        _query_for_owner(owner_id)
        .where(StorageRecommendation.id == recommendation_id)
        .execution_options(populate_existing=True)
    ).first()
    db.commit()
    if row is None:
        raise _not_found()
    return _to_out(*row)


# ---- W10: refresh, list, dismiss ----


def refresh(db: Session, owner_id: uuid.UUID, now: datetime | None = None) -> RecommendationList:
    """Re-evaluate the current version of every ACTIVE document (S3_MISSING versions skipped).

    One transaction, no storage call. Documents are row-locked; a document with an
    operation in flight (`pending_op`) is left untouched so an Apply in progress keeps
    its OPEN recommendation.
    """
    now = now or _utcnow()
    docs = db.scalars(
        select(Document)
        .where(Document.owner_id == owner_id, Document.status == "ACTIVE")
        .order_by(Document.id)
        .with_for_update()
    ).all()
    created: list[StorageRecommendation] = []
    for doc in docs:
        if doc.pending_op is not None:
            continue
        version = db.get(DocumentVersion, doc.current_version_id)
        if version is None or version.state != "ACTIVE":
            continue
        version_ids = select(DocumentVersion.id).where(DocumentVersion.document_id == doc.id)
        for old in db.scalars(
            select(StorageRecommendation).where(
                StorageRecommendation.version_id.in_(version_ids), StorageRecommendation.status == "OPEN"
            )
        ):
            old.status, old.resolved_at = "STALE", now
        db.flush()
        result = evaluate_version(db, version, now)
        if result.is_recommendation:
            rec = StorageRecommendation(
                version_id=version.id,
                current_class=version.storage_class,
                recommended_class=result.target,
                rule_id=result.rule_id,
                reason=result.reason,
                signals=result.signals,
                status="OPEN",
            )
            db.add(rec)
            created.append(rec)
    db.commit()
    ids = [r.id for r in created]
    return list_recommendations(db, owner_id, "open", only_ids=ids)


def list_recommendations(
    db: Session, owner_id: uuid.UUID, status: RecStatus = "open", only_ids: list[uuid.UUID] | None = None
) -> RecommendationList:
    query = _query_for_owner(owner_id).where(StorageRecommendation.status == status.upper())
    if only_ids is not None:
        query = query.where(StorageRecommendation.id.in_(only_ids))
    rows = db.execute(query.order_by(StorageRecommendation.created_at.desc(), Document.display_name)).all()
    db.commit()
    return RecommendationList(items=[_to_out(*r) for r in rows])


def dismiss(db: Session, owner_id: uuid.UUID, recommendation_id: uuid.UUID) -> RecommendationOut:
    """OPEN -> DISMISSED. Idempotent: any other status is returned unchanged."""
    row = db.execute(
        _query_for_owner(owner_id).where(StorageRecommendation.id == recommendation_id).with_for_update(
            of=StorageRecommendation
        )
    ).first()
    if row is None:
        db.rollback()
        raise _not_found()
    rec = row[0]
    if rec.status == "OPEN":
        rec.status, rec.resolved_at = "DISMISSED", _utcnow()
    db.commit()
    return _get_out(db, owner_id, recommendation_id)


# ---- W11: apply ----


def apply(
    db: Session, storage: ObjectStorage, owner_id: uuid.UUID, recommendation_id: uuid.UUID
) -> RecommendationOut:
    """Copy the current version to the recommended class in the simulated store (W11).

    Steps and crash recovery are described in app/services/apply_recovery.py.
    """
    found = db.execute(
        select(Document.id)
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .join(StorageRecommendation, StorageRecommendation.version_id == DocumentVersion.id)
        .where(StorageRecommendation.id == recommendation_id, Document.owner_id == owner_id,
               Document.status.in_(VISIBLE_STATUSES))
    ).first()
    db.commit()  # the request session holds no connection while waiting for the lock
    if found is None:
        raise _not_found()
    document_id = found[0]

    with document_lock(document_id):
        recover_interrupted(db, storage, owner_id, document_id)

        # Step 1: re-read everything under the lock; never trust the caller's copy.
        doc = db.get(Document, document_id, with_for_update=True, populate_existing=True)
        rec = db.get(StorageRecommendation, recommendation_id, with_for_update=True, populate_existing=True)
        if rec is None or doc is None or doc.owner_id != owner_id or doc.status not in VISIBLE_STATUSES:
            db.rollback()
            raise _not_found()
        if rec.status == "APPLIED":
            db.commit()
            return _get_out(db, owner_id, recommendation_id)  # W11: already applied is a 200 no-op
        if rec.status != "OPEN":
            db.rollback()
            raise _stale(f"The recommendation is {rec.status.lower()}; refresh recommendations")
        version = db.get(DocumentVersion, doc.current_version_id, populate_existing=True)
        now = _utcnow()
        still_valid = (
            doc.status == "ACTIVE"
            and version is not None
            and version.id == rec.version_id
            and version.state == "ACTIVE"
            and version.storage_class == rec.current_class
            and _matches(rec, evaluate_version(db, version, now))
        )
        if not still_valid:
            rec.status, rec.resolved_at = "STALE", now
            db.commit()
            raise _stale()
        doc.pending_op, doc.pending_op_at = "APPLY", now
        db.commit()
        key, version_id, old_store_id, target = doc.s3_key, version.id, version.s3_version_id, rec.recommended_class

        # Step 2: the copy. On failure nothing changed: drop the intent.
        try:
            copied = storage.copy_object(key, old_store_id, storage_class=target)
        except (NoSuchVersion, MethodNotAllowed) as exc:
            _mark_missing_and_stale(db, version_id, recommendation_id)
            clear_apply_intent(db, document_id)
            raise AppError("VERSION_EXPIRED", 410, "This version is no longer in storage") from exc
        except BaseException:
            _safe(clear_apply_intent, db, document_id)
            raise

        # Step 3: adopt the copy. A failure here leaves state B: the next operation on the
        # document (including a retried Apply) rolls it forward.
        finalize_apply(db, version_id, recommendation_id, copied.version_id, target)

        # Steps 4-5: cleanup. The Apply already took effect, so failures here are logged and
        # left to recovery (states C and D) rather than reported as a failed Apply.
        try:
            storage.delete_version(key, old_store_id)
            clear_apply_intent(db, document_id)
        except Exception:
            db.rollback()
            logger.exception("Apply on %s finished; old version cleanup left to recovery", document_id)
    return _get_out(db, owner_id, recommendation_id)


def _mark_missing_and_stale(db: Session, version_id: uuid.UUID, recommendation_id: uuid.UUID) -> None:
    try:
        version = db.get(DocumentVersion, version_id, with_for_update=True, populate_existing=True)
        if version.state == "ACTIVE":
            version.state = "S3_MISSING"
        rec = db.get(StorageRecommendation, recommendation_id, with_for_update=True, populate_existing=True)
        if rec.status == "OPEN":
            rec.status, rec.resolved_at = "STALE", _utcnow()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not record missing version %s", version_id)


def _safe(fn, *args) -> None:
    try:
        fn(*args)
    except Exception:
        logger.exception("Cleanup step %s failed; recovery will handle it", fn.__name__)

