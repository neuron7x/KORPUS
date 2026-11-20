"""Protect competency edges and serialize PostgreSQL graph edits with publication.

Revision ID: 0027_learning_competency_integrity
Revises: 0026_learning_history_integrity

Existing populated deployments still require independent retirement admission.
This guard prevents future mutation; it cannot reconstruct previously changed edges.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027_learning_competency_integrity"
down_revision: str | None = "0026_learning_history_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from korpus.infrastructure.learning_competency_schema import install_competency_guards
    from korpus.infrastructure.learning_history_concurrency import (
        install_postgres_learning_history_locks,
    )

    connection = op.get_bind()
    orphan = connection.exec_driver_sql(
        "SELECT c.course_version_id FROM learning_objective_competencies c "
        "LEFT JOIN learning_publications p ON p.course_version_id = c.course_version_id "
        "WHERE p.course_version_id IS NULL LIMIT 1"
    ).first()
    if orphan is not None:
        raise RuntimeError(
            "LEARNING_HISTORY_REQUIRES_RECONCILIATION: competency edge has no lifecycle"
        )
    if connection.dialect.name == "postgresql":
        install_postgres_learning_history_locks(connection)
    install_competency_guards(connection)


def downgrade() -> None:
    raise RuntimeError(
        "learning competency guard removal requires an independently retired deployment"
    )
