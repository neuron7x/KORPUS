"""a version is identified by its revision, not by its bytes

The unique constraint on (document_id, source_hash) made two revisions of one document
mutually exclusive whenever the text was unchanged — a re-issue that only moves the
effective dates could not be stored at all, and the ingest path hid this by returning
the existing row as a duplicate. The corpus's own name for a distinct state of a
document is the revision, so that is what must be unique.

Revision ID: 0010_revision_identity
Revises: 0009_reviewer_credentials
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_revision_identity"
down_revision: str | None = "0009_reviewer_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("document_versions") as batch:
        batch.drop_constraint("uq_version_document_source_hash", type_="unique")
        batch.create_unique_constraint("uq_version_document_revision", ["document_id", "revision"])


def downgrade() -> None:
    with op.batch_alter_table("document_versions") as batch:
        batch.drop_constraint("uq_version_document_revision", type_="unique")
        batch.create_unique_constraint(
            "uq_version_document_source_hash", ["document_id", "source_hash"]
        )
