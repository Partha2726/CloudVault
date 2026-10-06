"""simulated S3 store (AM-7) and durable job queue columns on processing_jobs

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05 21:21:24.479775
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('sim_object_versions',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('bucket', sa.String(length=63), nullable=False),
    sa.Column('key', sa.String(length=1024), nullable=False),
    sa.Column('version_id', sa.String(length=64), nullable=False),
    sa.Column('is_delete_marker', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=True),
    sa.Column('etag', sa.String(length=80), nullable=True),
    sa.Column('checksum_sha256', sa.String(length=64), nullable=True),
    sa.Column('storage_class', sa.String(length=20), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('last_modified', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("storage_class IS NULL OR storage_class IN ('STANDARD', 'STANDARD_IA', 'GLACIER_IR')", name='ck_sim_storage_class'),
    sa.CheckConstraint('(is_delete_marker AND data IS NULL AND size_bytes = 0 AND storage_class IS NULL AND etag IS NULL AND checksum_sha256 IS NULL AND content_type IS NULL) OR (NOT is_delete_marker AND data IS NOT NULL AND size_bytes = octet_length(data) AND storage_class IS NOT NULL AND etag IS NOT NULL AND checksum_sha256 IS NOT NULL AND content_type IS NOT NULL)', name='ck_sim_marker_shape'),
    sa.CheckConstraint('char_length(key) >= 1', name='ck_sim_key_nonempty'),
    sa.CheckConstraint('size_bytes >= 0', name='ck_sim_size_nonnegative'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('version_id')
    )
    op.create_index('ix_sim_bucket_key_id', 'sim_object_versions', ['bucket', 'key', sa.literal_column('id DESC')], unique=False)
    op.add_column('processing_jobs', sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('processing_jobs', sa.Column('deliveries', sa.Integer(), server_default='0', nullable=False))
    op.create_check_constraint('ck_jobs_deliveries', 'processing_jobs', 'deliveries >= 0')
    op.create_index('ix_jobs_pending_created', 'processing_jobs', ['created_at'], unique=False, postgresql_where=sa.text("status = 'PENDING'"))


def downgrade() -> None:
    op.drop_index('ix_jobs_pending_created', table_name='processing_jobs', postgresql_where=sa.text("status = 'PENDING'"))
    op.drop_constraint('ck_jobs_deliveries', 'processing_jobs', type_='check')
    op.drop_column('processing_jobs', 'deliveries')
    op.drop_column('processing_jobs', 'claimed_at')
    op.drop_index('ix_sim_bucket_key_id', table_name='sim_object_versions')
    op.drop_table('sim_object_versions')
