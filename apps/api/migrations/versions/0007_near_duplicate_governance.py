"""near-duplicate fingerprint and reviewer acknowledgement

Revision ID: 0007_near_duplicate_governance
Revises: 0006_source_authenticity
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_near_duplicate_governance"
down_revision: str | None = "0006_source_authenticity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("document_versions") as batch:
        batch.add_column(
            sa.Column(
                "content_fingerprint",
                sa.String(16),
                nullable=False,
                server_default="0000000000000000",
            )
        )
        batch.add_column(
            sa.Column(
                "near_duplicate_of_version_id",
                sa.String(36),
                sa.ForeignKey(
                    "document_versions.id",
                    name="fk_document_versions_near_duplicate_of_version_id",
                ),
            )
        )
        batch.add_column(sa.Column("near_duplicate_similarity", sa.Float()))
        batch.add_column(sa.Column("near_duplicate_acknowledged_by", sa.String(200)))
    op.create_index(
        "ix_document_versions_content_fingerprint",
        "document_versions",
        ["content_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_versions_content_fingerprint", table_name="document_versions")
    with op.batch_alter_table("document_versions") as batch:
        batch.drop_column("near_duplicate_acknowledged_by")
        batch.drop_column("near_duplicate_similarity")
        batch.drop_column("near_duplicate_of_version_id")
        batch.drop_column("content_fingerprint")
