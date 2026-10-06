"""[S3-SIM] Simulated S3 object store tables (doc 15, AM-7).

These tables play the role of Amazon S3. They have no foreign keys to the application
tables: S3 knows nothing about CloudVault's documents.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db import Base

SIM_STORAGE_CLASSES = ("STANDARD", "STANDARD_IA", "GLACIER_IR")


class SimObjectVersion(Base):
    """One object version or delete marker. The latest version of a key is its highest `id`."""

    __tablename__ = "sim_object_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    key: Mapped[str] = mapped_column(String(1024), nullable=False)
    version_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    is_delete_marker: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Bytes are loaded only when explicitly requested (GET, copy).
    data: Mapped[bytes | None] = deferred(mapped_column(LargeBinary))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    content_type: Mapped[str | None] = mapped_column(String(100))
    etag: Mapped[str | None] = mapped_column(String(80))
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    storage_class: Mapped[str | None] = mapped_column(String(20))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    last_modified: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="ck_sim_size_nonnegative"),
        CheckConstraint(
            "storage_class IS NULL OR storage_class IN ('STANDARD', 'STANDARD_IA', 'GLACIER_IR')",
            name="ck_sim_storage_class",
        ),
        # A delete marker has no data, size, type, checksum or class; an object version has all of them.
        CheckConstraint(
            "(is_delete_marker AND data IS NULL AND size_bytes = 0 AND storage_class IS NULL "
            "AND etag IS NULL AND checksum_sha256 IS NULL AND content_type IS NULL) OR "
            "(NOT is_delete_marker AND data IS NOT NULL AND size_bytes = octet_length(data) "
            "AND storage_class IS NOT NULL AND etag IS NOT NULL AND checksum_sha256 IS NOT NULL "
            "AND content_type IS NOT NULL)",
            name="ck_sim_marker_shape",
        ),
        CheckConstraint("char_length(key) >= 1", name="ck_sim_key_nonempty"),
        Index("ix_sim_bucket_key_id", "bucket", "key", text("id DESC")),
    )
