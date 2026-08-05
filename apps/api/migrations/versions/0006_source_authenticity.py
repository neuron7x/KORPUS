"""detached source authenticity metadata

Revision ID: 0006_source_authenticity
Revises: 0005_durable_ingestion_jobs
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_source_authenticity"
down_revision: str | None = "0005_durable_ingestion_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("document_versions") as batch:
        batch.add_column(sa.Column("source_key_id", sa.String(200)))
        batch.add_column(sa.Column("source_signature_b64", sa.Text()))
    op.create_index("ix_document_versions_source_key_id", "document_versions", ["source_key_id"])


def downgrade() -> None:
    op.drop_index("ix_document_versions_source_key_id", table_name="document_versions")
    with op.batch_alter_table("document_versions") as batch:
        batch.drop_column("source_signature_b64")
        batch.drop_column("source_key_id")
