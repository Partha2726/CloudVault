"""document_versions.s3_version_id NOT NULL; version states ACTIVE and S3_MISSING only (AM-9)

A version row is now inserted only after the store write succeeded, so it always has the
store's version id. Rows left in the withdrawn PENDING or FAILED states never held stored
data the application exposed (never current, never listed, no job, access log or
recommendation), so they are removed before the column is tightened. The downgrade
restores the AM-1 shape but cannot bring those rows back.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM document_versions WHERE state IN ('PENDING', 'FAILED')")
    op.drop_index('ix_versions_state_created', table_name='document_versions', postgresql_where=sa.text("state = 'PENDING'"))
    op.drop_constraint('ck_versions_s3_id_when_stored', 'document_versions', type_='check')
    op.drop_constraint('ck_versions_state', 'document_versions', type_='check')
    op.create_check_constraint('ck_versions_state', 'document_versions', "state IN ('ACTIVE', 'S3_MISSING')")
    op.alter_column('document_versions', 'state', server_default='ACTIVE')
    op.alter_column('document_versions', 's3_version_id', existing_type=sa.String(length=64), nullable=False)


def downgrade() -> None:
    op.alter_column('document_versions', 's3_version_id', existing_type=sa.String(length=64), nullable=True)
    op.alter_column('document_versions', 'state', server_default='PENDING')
    op.drop_constraint('ck_versions_state', 'document_versions', type_='check')
    op.create_check_constraint(
        'ck_versions_state', 'document_versions', "state IN ('PENDING', 'ACTIVE', 'FAILED', 'S3_MISSING')"
    )
    op.create_check_constraint(
        'ck_versions_s3_id_when_stored', 'document_versions', "state IN ('PENDING', 'FAILED') OR s3_version_id IS NOT NULL"
    )
    op.create_index('ix_versions_state_created', 'document_versions', ['state', 'created_at'], unique=False, postgresql_where=sa.text("state = 'PENDING'"))
