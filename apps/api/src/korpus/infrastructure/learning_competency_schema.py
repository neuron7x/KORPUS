"""Competency edges belong to the immutable published course graph."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Column, ForeignKeyConstraint, MetaData, String, Table, event
from sqlalchemy.engine import Connection

from korpus.infrastructure.schema import metadata

learning_objective_competencies = Table(
    "learning_objective_competencies",
    metadata,
    Column("course_version_id", String(128), primary_key=True),
    Column("lesson_id", String(128), primary_key=True),
    Column("objective_id", String(128), primary_key=True),
    Column("competency_id", String(128), primary_key=True),
    ForeignKeyConstraint(
        ["course_version_id", "lesson_id", "objective_id"],
        [
            "learning_objectives.course_version_id",
            "learning_objectives.lesson_id",
            "learning_objectives.id",
        ],
        ondelete="CASCADE",
    ),
)


def _sqlite_guards() -> tuple[tuple[str, str], ...]:
    guards = []
    for operation, versions in (
        ("INSERT", "NEW.course_version_id"),
        ("UPDATE", "OLD.course_version_id, NEW.course_version_id"),
        ("DELETE", "OLD.course_version_id"),
    ):
        name = f"trg_learning_competency_{operation.lower()}"
        guards.append(
            (
                name,
                f"CREATE TRIGGER {name} BEFORE {operation} "
                "ON learning_objective_competencies "
                "WHEN EXISTS (SELECT 1 FROM learning_publications "
                f"WHERE course_version_id IN ({versions}) "
                "AND state IN ('published', 'invalidated', 'retired')) "
                "BEGIN SELECT RAISE(ABORT, 'published learning history is immutable'); END",
            )
        )
    return tuple(guards)


def install_competency_guards(connection: Connection) -> None:
    """Install through the forward migration; never reconstruct existing history."""
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE TRIGGER trg_korpus_learning_immutable_learning_objective_competencies "
            "BEFORE INSERT OR UPDATE OR DELETE ON public.learning_objective_competencies "
            "FOR EACH ROW EXECUTE FUNCTION public.korpus_guard_learning_content_immutable()"
        )
    elif connection.dialect.name == "sqlite":
        for name, statement in _sqlite_guards():
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
            connection.exec_driver_sql(statement)
    else:
        raise RuntimeError("unsupported learning competency migration dialect")


def _install_sqlite_bootstrap(_metadata: MetaData, connection: Connection, **kwargs: Any) -> None:
    if connection.dialect.name == "sqlite" and learning_objective_competencies in kwargs.get(
        "tables", ()
    ):
        install_competency_guards(connection)


# Historical migrations create individual tables. Only metadata.create_all is
# the SQLite development/test bootstrap; migrations install guards in 0027.
event.listen(metadata, "after_create", _install_sqlite_bootstrap)
