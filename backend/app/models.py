"""Six application tables (doc 04) with the AM-1 state model (docs/15-amendments.md).

Writes that need the store never hold a transaction open across the store call. A new
document is first committed as PENDING (reserving its name), the store operation runs,
then a second short transaction inserts the version row with the store's version id and
marks the document ACTIVE (or FAILED on error). A version row is only ever inserted after
the store write succeeded, so `document_versions.s3_version_id` is NOT NULL (AM-9).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

DOCUMENT_STATUSES = ("PENDING", "ACTIVE", "DELETED", "FAILED")
PENDING_OPS = ("DELETE", "UNDELETE", "PURGE", "APPLY")
VERSION_STATES = ("ACTIVE", "S3_MISSING")
VERSION_ORIGINS = ("UPLOAD", "RESTORE")
JOB_STATUSES = ("PENDING", "SUCCEEDED", "FAILED", "SKIPPED")
REC_STATUSES = ("OPEN", "APPLIED", "DISMISSED", "STALE")
REC_CLASSES = ("STANDARD", "STANDARD_IA", "GLACIER_IR")
REC_RULES = ("R1_PROMOTE", "R2_TO_GIR", "R3_TO_IA")
ACCESS_EVENTS = ("DOWNLOAD",)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now(nullable: bool = False) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=nullable, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (Index("uq_users_email_lower", func.lower(email), unique=True),)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="PENDING")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", use_alter=True, name="fk_documents_current_version"),
    )
    delete_marker_version_id: Mapped[str | None] = mapped_column(String(64))
    pending_op: Mapped[str | None] = mapped_column(String(10))
    pending_op_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(_in("status", DOCUMENT_STATUSES), name="ck_documents_status"),
        CheckConstraint(f"pending_op IS NULL OR {_in('pending_op', PENDING_OPS)}", name="ck_documents_pending_op"),
        CheckConstraint("(pending_op IS NULL) = (pending_op_at IS NULL)", name="ck_documents_pending_op_at"),
        # A visible document always has a stored current version; a trashed one has its marker.
        CheckConstraint(
            "status IN ('PENDING', 'FAILED') OR current_version_id IS NOT NULL", name="ck_documents_current_version"
        ),
        CheckConstraint(
            "(status = 'DELETED' AND deleted_at IS NOT NULL AND delete_marker_version_id IS NOT NULL) OR "
            "(status <> 'DELETED' AND deleted_at IS NULL AND delete_marker_version_id IS NULL)",
            name="ck_documents_deleted_fields",
        ),
        # A PENDING document reserves its name too, so concurrent same-name creates fail before S3.
        Index(
            "uq_documents_owner_name_live",
            "owner_id",
            func.lower(display_name),
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'ACTIVE')"),
        ),
        Index("ix_documents_owner_status", "owner_id", "status"),
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    s3_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    storage_class: Mapped[str] = mapped_column(String(20), nullable=False, server_default="STANDARD")
    storage_class_changed_at: Mapped[datetime] = _now()
    origin: Mapped[str] = mapped_column(String(10), nullable=False, server_default="UPLOAD")
    restored_from_version: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(12), nullable=False, server_default="ACTIVE")
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_versions_size_positive"),
        CheckConstraint("version_number >= 1", name="ck_versions_number_positive"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_versions_sha256_hex"),
        CheckConstraint(_in("state", VERSION_STATES), name="ck_versions_state"),
        CheckConstraint(_in("origin", VERSION_ORIGINS), name="ck_versions_origin"),
        CheckConstraint(
            "(origin = 'RESTORE') = (restored_from_version IS NOT NULL)", name="ck_versions_restore_source"
        ),
        UniqueConstraint("document_id", "version_number", name="uq_versions_doc_number"),
        UniqueConstraint("document_id", "s3_version_id", name="uq_versions_doc_s3_version"),
        Index("ix_versions_doc_created", "document_id", "created_at"),
    )


class AccessLog(Base):
    __tablename__ = "access_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(12), nullable=False, server_default="DOWNLOAD")
    accessed_at: Mapped[datetime] = _now()

    __table_args__ = (
        CheckConstraint(_in("event_type", ACCESS_EVENTS), name="ck_access_logs_event_type"),
        Index("ix_access_logs_version_time", "version_id", text("accessed_at DESC")),
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(500))
    page_count: Mapped[int | None] = mapped_column(Integer)
    word_count: Mapped[int | None] = mapped_column(Integer)
    text_excerpt: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Durable queue (AM-7): worker lease and delivery count; `attempts` counts manual retries.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deliveries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUSES), name="ck_jobs_status"),
        CheckConstraint("attempts >= 0", name="ck_jobs_attempts"),
        CheckConstraint("deliveries >= 0", name="ck_jobs_deliveries"),
        Index("ix_jobs_pending_created", "created_at", postgresql_where=text("status = 'PENDING'")),
        CheckConstraint("(status = 'PENDING') = (finished_at IS NULL)", name="ck_jobs_finished_at"),
        CheckConstraint("text_excerpt IS NULL OR char_length(text_excerpt) <= 4000", name="ck_jobs_excerpt_len"),
    )


class StorageRecommendation(Base):
    __tablename__ = "storage_recommendations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    current_class: Mapped[str] = mapped_column(String(20), nullable=False)
    recommended_class: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    signals: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="OPEN")
    created_at: Mapped[datetime] = _now()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(_in("status", REC_STATUSES), name="ck_recs_status"),
        CheckConstraint(_in("recommended_class", REC_CLASSES), name="ck_recs_recommended_class"),
        CheckConstraint(_in("rule_id", REC_RULES), name="ck_recs_rule_id"),
        CheckConstraint("current_class <> recommended_class", name="ck_recs_class_changes"),
        CheckConstraint("(status = 'OPEN') = (resolved_at IS NULL)", name="ck_recs_resolved_at"),
        Index("uq_recs_open_per_version", "version_id", unique=True, postgresql_where=text("status = 'OPEN'")),
    )
