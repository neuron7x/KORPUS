"""persist evidence-bound learner mastery projection

Revision ID: 0017_learning_mastery
Revises: 0016_learning_course_graph
"""

from __future__ import annotations

from collections.abc import Sequence
from alembic import op
from korpus.infrastructure.learning_schema import learning_mastery

revision: str = "0017_learning_mastery"
down_revision: str | None = "0016_learning_course_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    learning_mastery.create(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    learning_mastery.drop(op.get_bind(), checkfirst=False)
