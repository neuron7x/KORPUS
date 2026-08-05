"""deterministic extraction quality findings and reviewer acknowledgement

Revision ID: 0008_extraction_quality_gov
Revises: 0007_near_duplicate_governance
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_extraction_quality_gov"
down_revision: str | None = "0007_near_duplicate_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("document_versions") as batch:
        batch.add_column(
            sa.Column("extraction_text_chars", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("extraction_alnum_ratio", sa.Float(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column(
                "extraction_replacement_ratio", sa.Float(), nullable=False, server_default="0"
            )
        )
        batch.add_column(
            sa.Column(
                "extraction_quality_flags_json", sa.Text(), nullable=False, server_default="[]"
            )
        )
        batch.add_column(sa.Column("extraction_quality_acknowledged_by", sa.String(200)))


def downgrade() -> None:
    with op.batch_alter_table("document_versions") as batch:
        batch.drop_column("extraction_quality_acknowledged_by")
        batch.drop_column("extraction_quality_flags_json")
        batch.drop_column("extraction_replacement_ratio")
        batch.drop_column("extraction_alnum_ratio")
        batch.drop_column("extraction_text_chars")
