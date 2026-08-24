"""content-addressed reviewer credentials for governed transitions

Revision ID: 0009_reviewer_credentials
Revises: 0008_extraction_quality_gov
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_reviewer_credentials"
down_revision: str | None = "0008_extraction_quality_gov"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("document_versions") as batch:
        batch.add_column(sa.Column("metadata_reviewer_credential_id", sa.String(200)))
        batch.add_column(sa.Column("content_reviewer_credential_id", sa.String(200)))
        batch.add_column(sa.Column("approver_credential_id", sa.String(200)))


def downgrade() -> None:
    with op.batch_alter_table("document_versions") as batch:
        batch.drop_column("approver_credential_id")
        batch.drop_column("content_reviewer_credential_id")
        batch.drop_column("metadata_reviewer_credential_id")
