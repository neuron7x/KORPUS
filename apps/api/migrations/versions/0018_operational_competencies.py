"""persist operational competency framework revisions

Revision ID: 0018_operational_competencies
Revises: 0017_learning_mastery
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import Column, String, inspect

from korpus.infrastructure.competency_schema import COMPETENCY_TABLES
from korpus.infrastructure.learning_schema import learning_objective_competencies

revision: str = "0018_operational_competencies"
down_revision: str | None = "0017_learning_mastery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in COMPETENCY_TABLES:
        table.create(op.get_bind(), checkfirst=False)
    existing_columns = {
        item["name"] for item in inspect(op.get_bind()).get_columns("learning_course_versions")
    }
    if "competency_framework_id" not in existing_columns:
        op.add_column("learning_course_versions", Column("competency_framework_id", String(128)))
    if "competency_framework_revision" not in existing_columns:
        op.add_column(
            "learning_course_versions", Column("competency_framework_revision", String(120))
        )
    # Migration 0016 imports the live table registry, so a clean bootstrap may already
    # contain this newly registered child table; an upgrade from 0017 does not.
    learning_objective_competencies.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    learning_objective_competencies.drop(op.get_bind(), checkfirst=False)
    op.drop_column("learning_course_versions", "competency_framework_revision")
    op.drop_column("learning_course_versions", "competency_framework_id")
    for table in reversed(COMPETENCY_TABLES):
        table.drop(op.get_bind(), checkfirst=False)
