"""Processing status and retry (doc 05.5, W16; AM-7 durable queue).

Retry resets a job so the T17 worker processes it again; it never creates a second job
(`processing_jobs.version_id` is unique, AM-2). It runs in one short, row-locked
transaction and touches only the job row; an in-flight delivery of the old attempt can no
longer finish it, because its lease (`claimed_at`, `deliveries`) no longer matches.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Document, DocumentVersion, ProcessingJob
from app.schemas import ProcessingItem, ProcessingList
from app.services.document_service import LISTED_VERSION_STATES, STALL_AFTER, VISIBLE_STATUSES


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _is_stalled(job: ProcessingJob, now: datetime) -> bool:
    return job.status == "PENDING" and job.created_at < now - STALL_AFTER


def _item(job: ProcessingJob, version_number: int, now: datetime) -> ProcessingItem:
    return ProcessingItem(
        version_number=version_number,
        status=job.status,
        attempts=job.attempts,
        error_code=job.error_code,
        page_count=job.page_count,
        word_count=job.word_count,
        stalled=_is_stalled(job, now),
    )


def _document(db: Session, owner_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.owner_id == owner_id, Document.status.in_(VISIBLE_STATUSES)
        )
    )
    if doc is None:
        db.rollback()
        raise AppError("NOT_FOUND", 404, "Document not found")
    return doc


def list_jobs(db: Session, owner_id: uuid.UUID, document_id: uuid.UUID, now: datetime | None = None) -> ProcessingList:
    """One item per listed version (ACTIVE or S3_MISSING), newest version first."""
    now = now or _utcnow()
    doc = _document(db, owner_id, document_id)
    rows = db.execute(
        select(ProcessingJob, DocumentVersion.version_number)
        .join(DocumentVersion, DocumentVersion.id == ProcessingJob.version_id)
        .where(DocumentVersion.document_id == doc.id, DocumentVersion.state.in_(LISTED_VERSION_STATES))
        .order_by(DocumentVersion.version_number.desc())
    ).all()
    db.commit()
    return ProcessingList(items=[_item(job, n, now) for job, n in rows])


def retry(
    db: Session, owner_id: uuid.UUID, document_id: uuid.UUID, version_number: int | None, now: datetime | None = None
) -> ProcessingItem:
    """W16. FAILED or stalled PENDING -> PENDING again. PENDING and not stalled: no-op.

    SUCCEEDED/SKIPPED: 409 JOB_NOT_RETRYABLE. A version no longer stored: 410 VERSION_EXPIRED.
    The retried job's `created_at` restarts the 10-minute stall clock.
    """
    now = now or _utcnow()
    doc = _document(db, owner_id, document_id)
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
        db.rollback()
        raise AppError("VERSION_NOT_FOUND", 404, "Version not found")
    if version.state == "S3_MISSING":
        db.rollback()
        raise AppError("VERSION_EXPIRED", 410, "This version is no longer in storage")
    job = db.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.version_id == version.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        db.rollback()
        raise AppError("NOT_FOUND", 404, "No processing job for this version")
    if job.status in ("SUCCEEDED", "SKIPPED"):
        db.rollback()
        raise AppError("JOB_NOT_RETRYABLE", 409, f"The job already {job.status.lower()}")
    if job.status == "FAILED" or _is_stalled(job, now):
        job.status = "PENDING"
        job.attempts += 1
        job.deliveries = 0
        job.claimed_at = None
        job.finished_at = None
        job.error_code = job.error_message = None
        job.page_count = job.word_count = None
        job.text_excerpt = None
        job.created_at = now
    item = _item(job, version.version_number, now)
    db.commit()
    return item
