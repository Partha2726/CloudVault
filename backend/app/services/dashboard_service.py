"""Dashboard summary (doc 05.5 `GET /dashboard/summary`, doc 06.5). [APP] figures from the DB.

Scope: the owner's ACTIVE documents and their ACTIVE versions (S3_MISSING versions are no
longer stored; trashed documents are excluded). `bytes_by_class` sums every stored version,
so its total equals `total_bytes_all_versions`. Access counts are CloudVault's own log.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import JOB_STATUSES, AccessLog, Document, DocumentVersion, ProcessingJob, StorageRecommendation
from app.schemas import DashboardSummary
from app.storage.base import STORAGE_CLASSES


def summary(db: Session, owner_id: uuid.UUID, now: datetime | None = None) -> DashboardSummary:
    now = now or datetime.now(UTC)
    active_docs = select(Document.id).where(Document.owner_id == owner_id, Document.status == "ACTIVE")
    stored = (DocumentVersion.document_id.in_(active_docs), DocumentVersion.state == "ACTIVE")

    document_count = db.scalar(select(func.count()).select_from(active_docs.subquery()))
    current_bytes = db.scalar(
        select(func.coalesce(func.sum(DocumentVersion.size_bytes), 0))
        .join(Document, Document.current_version_id == DocumentVersion.id)
        .where(Document.owner_id == owner_id, Document.status == "ACTIVE", DocumentVersion.state == "ACTIVE")
    )
    by_class = dict(
        db.execute(
            select(DocumentVersion.storage_class, func.sum(DocumentVersion.size_bytes))
            .where(*stored)
            .group_by(DocumentVersion.storage_class)
        ).all()
    )
    accesses_30d = db.scalar(
        select(func.count(AccessLog.id)).where(
            AccessLog.document_id.in_(active_docs), AccessLog.accessed_at >= now - timedelta(days=30)
        )
    )
    open_recommendations = db.scalar(
        select(func.count(StorageRecommendation.id))
        .join(DocumentVersion, DocumentVersion.id == StorageRecommendation.version_id)
        .where(StorageRecommendation.status == "OPEN", DocumentVersion.document_id.in_(active_docs))
    )
    jobs = dict(
        db.execute(
            select(ProcessingJob.status, func.count(ProcessingJob.id))
            .join(DocumentVersion, DocumentVersion.id == ProcessingJob.version_id)
            .where(*stored)
            .group_by(ProcessingJob.status)
        ).all()
    )
    db.commit()
    bytes_by_class = {c: int(by_class.get(c, 0)) for c in STORAGE_CLASSES}
    return DashboardSummary(
        document_count=document_count or 0,
        current_bytes=int(current_bytes or 0),
        total_bytes_all_versions=sum(bytes_by_class.values()),
        accesses_30d=accesses_30d or 0,
        bytes_by_class=bytes_by_class,
        open_recommendations=open_recommendations or 0,
        jobs_by_status={s: int(jobs.get(s, 0)) for s in JOB_STATUSES},
    )
