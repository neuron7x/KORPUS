"""widen Alembic revision storage before long revision identifiers

Revision ID: 0016a_alembic_version_width
Revises: 0016_temporal_corpus_snapshot
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016a_alembic_version_width"
down_revision: str | None = "0016_temporal_corpus_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE alembic_version "
        "ALTER COLUMN version_num TYPE VARCHAR(128)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE alembic_version "
        "ALTER COLUMN version_num TYPE VARCHAR(32)"
    )
