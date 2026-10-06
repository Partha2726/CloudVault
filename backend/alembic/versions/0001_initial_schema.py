"""initial schema: six tables of doc 04 with the AM-1 state model

Revision ID: 0001
Revises:
Create Date: 2026-10-05 20:48:14.278383
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('uq_users_email_lower', 'users', [sa.literal_column('lower(email)')], unique=True)
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('s3_key', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=10), server_default='PENDING', nullable=False),
    sa.Column('current_version_id', sa.UUID(), nullable=True),
    sa.Column('delete_marker_version_id', sa.String(length=64), nullable=True),
    sa.Column('pending_op', sa.String(length=10), nullable=True),
    sa.Column('pending_op_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'DELETED' AND deleted_at IS NOT NULL AND delete_marker_version_id IS NOT NULL) OR (status <> 'DELETED' AND deleted_at IS NULL AND delete_marker_version_id IS NULL)", name='ck_documents_deleted_fields'),
    sa.CheckConstraint("pending_op IS NULL OR pending_op IN ('DELETE', 'UNDELETE', 'PURGE', 'APPLY')", name='ck_documents_pending_op'),
    sa.CheckConstraint("status IN ('PENDING', 'ACTIVE', 'DELETED', 'FAILED')", name='ck_documents_status'),
    sa.CheckConstraint("status IN ('PENDING', 'FAILED') OR current_version_id IS NOT NULL", name='ck_documents_current_version'),
    sa.CheckConstraint('(pending_op IS NULL) = (pending_op_at IS NULL)', name='ck_documents_pending_op_at'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('s3_key')
    )
    op.create_index(op.f('ix_documents_owner_id'), 'documents', ['owner_id'], unique=False)
    op.create_index('ix_documents_owner_status', 'documents', ['owner_id', 'status'], unique=False)
    op.create_index('uq_documents_owner_name_live', 'documents', ['owner_id', sa.literal_column('lower(display_name)')], unique=True, postgresql_where=sa.text("status IN ('PENDING', 'ACTIVE')"))
    op.create_table('document_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('s3_version_id', sa.String(length=64), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('sha256', sa.CHAR(length=64), nullable=False),
    sa.Column('storage_class', sa.String(length=20), server_default='STANDARD', nullable=False),
    sa.Column('storage_class_changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('origin', sa.String(length=10), server_default='UPLOAD', nullable=False),
    sa.Column('restored_from_version', sa.Integer(), nullable=True),
    sa.Column('state', sa.String(length=12), server_default='PENDING', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(origin = 'RESTORE') = (restored_from_version IS NOT NULL)", name='ck_versions_restore_source'),
    sa.CheckConstraint("origin IN ('UPLOAD', 'RESTORE')", name='ck_versions_origin'),
    sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name='ck_versions_sha256_hex'),
    sa.CheckConstraint("state IN ('PENDING', 'ACTIVE', 'FAILED', 'S3_MISSING')", name='ck_versions_state'),
    sa.CheckConstraint("state IN ('PENDING', 'FAILED') OR s3_version_id IS NOT NULL", name='ck_versions_s3_id_when_stored'),
    sa.CheckConstraint('size_bytes > 0', name='ck_versions_size_positive'),
    sa.CheckConstraint('version_number >= 1', name='ck_versions_number_positive'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 's3_version_id', name='uq_versions_doc_s3_version'),
    sa.UniqueConstraint('document_id', 'version_number', name='uq_versions_doc_number')
    )
    # Circular FK (documents <-> document_versions) added once both tables exist.
    op.create_foreign_key(
        'fk_documents_current_version', 'documents', 'document_versions', ['current_version_id'], ['id']
    )
    op.create_index('ix_versions_doc_created', 'document_versions', ['document_id', 'created_at'], unique=False)
    op.create_index('ix_versions_state_created', 'document_versions', ['state', 'created_at'], unique=False, postgresql_where=sa.text("state = 'PENDING'"))
    op.create_table('access_logs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('event_type', sa.String(length=12), server_default='DOWNLOAD', nullable=False),
    sa.Column('accessed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("event_type IN ('DOWNLOAD')", name='ck_access_logs_event_type'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_access_logs_version_time', 'access_logs', ['version_id', sa.literal_column('accessed_at DESC')], unique=False)
    op.create_table('processing_jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=10), server_default='PENDING', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error_code', sa.String(length=40), nullable=True),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('page_count', sa.Integer(), nullable=True),
    sa.Column('word_count', sa.Integer(), nullable=True),
    sa.Column('text_excerpt', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(status = 'PENDING') = (finished_at IS NULL)", name='ck_jobs_finished_at'),
    sa.CheckConstraint("status IN ('PENDING', 'SUCCEEDED', 'FAILED', 'SKIPPED')", name='ck_jobs_status'),
    sa.CheckConstraint('attempts >= 0', name='ck_jobs_attempts'),
    sa.CheckConstraint('text_excerpt IS NULL OR char_length(text_excerpt) <= 4000', name='ck_jobs_excerpt_len'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('version_id')
    )
    op.create_index(op.f('ix_processing_jobs_document_id'), 'processing_jobs', ['document_id'], unique=False)
    op.create_table('storage_recommendations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('current_class', sa.String(length=20), nullable=False),
    sa.Column('recommended_class', sa.String(length=20), nullable=False),
    sa.Column('rule_id', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('signals', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=10), server_default='OPEN', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(status = 'OPEN') = (resolved_at IS NULL)", name='ck_recs_resolved_at'),
    sa.CheckConstraint("recommended_class IN ('STANDARD', 'STANDARD_IA', 'GLACIER_IR')", name='ck_recs_recommended_class'),
    sa.CheckConstraint("rule_id IN ('R1_PROMOTE', 'R2_TO_GIR', 'R3_TO_IA')", name='ck_recs_rule_id'),
    sa.CheckConstraint("status IN ('OPEN', 'APPLIED', 'DISMISSED', 'STALE')", name='ck_recs_status'),
    sa.CheckConstraint('current_class <> recommended_class', name='ck_recs_class_changes'),
    sa.ForeignKeyConstraint(['version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('uq_recs_open_per_version', 'storage_recommendations', ['version_id'], unique=True, postgresql_where=sa.text("status = 'OPEN'"))


def downgrade() -> None:
    op.drop_index('uq_recs_open_per_version', table_name='storage_recommendations', postgresql_where=sa.text("status = 'OPEN'"))
    op.drop_table('storage_recommendations')
    op.drop_index(op.f('ix_processing_jobs_document_id'), table_name='processing_jobs')
    op.drop_table('processing_jobs')
    op.drop_index('ix_access_logs_version_time', table_name='access_logs')
    op.drop_table('access_logs')
    op.drop_index('ix_versions_state_created', table_name='document_versions', postgresql_where=sa.text("state = 'PENDING'"))
    op.drop_constraint('fk_documents_current_version', 'documents', type_='foreignkey')
    op.drop_index('ix_versions_doc_created', table_name='document_versions')
    op.drop_table('document_versions')
    op.drop_index('uq_documents_owner_name_live', table_name='documents', postgresql_where=sa.text("status IN ('PENDING', 'ACTIVE')"))
    op.drop_index('ix_documents_owner_status', table_name='documents')
    op.drop_index(op.f('ix_documents_owner_id'), table_name='documents')
    op.drop_table('documents')
    op.drop_index('uq_users_email_lower', table_name='users')
    op.drop_table('users')
