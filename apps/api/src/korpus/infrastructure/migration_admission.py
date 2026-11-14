"""Observed bootstrap and immutable historical-path admission for migrations.

This module does not certify N-1 compatibility or authenticate retirement.
Existing installations stay blocked until an independent retirement protocol exists.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from sqlalchemy import Connection, text

from korpus.infrastructure.corpus_snapshot_guards import require_guards
from korpus.infrastructure.migration_baseline_proof import (
    BaselineProof,
    proven_baseline_forward,
    verify_baseline,
    verify_passive_revision,
)

BOOTSTRAP_HEAD = "0025_sealed_provenance_integrity"
_MIGRATION_LOCK = 0x4B4F525055534D47


class MigrationAdmissionError(RuntimeError):
    """No observed state proves this migration is admissible."""


def preflight_source(source_root: Path) -> BaselineProof:
    """Reject unknown source before Alembic imports executable revision modules."""
    baseline = verify_baseline(source_root)
    files = list((source_root / "apps/api/migrations/versions").glob("*.py"))
    actual = {str(path.relative_to(source_root)) for path in files}
    expected = baseline.files | {f"apps/api/migrations/versions/{BOOTSTRAP_HEAD}.py"}
    if any(path.is_symlink() for path in files) or actual != expected:
        raise MigrationAdmissionError("DENIED_SOURCE_HISTORY_UNPROVEN")
    head = verify_passive_revision(source_root, BOOTSTRAP_HEAD, baseline.chain[-1])
    return replace(baseline, sources=(*baseline.sources, head))


def resolve_proven_target(destination: object, baseline: BaselineProof) -> str:
    """Resolve only raw canonical targets; Alembic resolution imports revision modules."""
    if destination == "head":
        return BOOTSTRAP_HEAD
    if isinstance(destination, str) and destination in (*baseline.chain, BOOTSTRAP_HEAD):
        return destination
    raise MigrationAdmissionError("DENIED_MIGRATION_TARGET_UNPROVEN")


@contextmanager
def migration_lock(connection: Connection) -> Iterator[None]:
    """Serialize cooperative migrators and retain one transaction through DDL."""
    with connection.begin():
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif connection.dialect.name == "postgresql":
            connection.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _MIGRATION_LOCK})
        else:
            raise MigrationAdmissionError("DENIED_DATABASE_DIALECT_UNPROVEN")
        yield


def _sqlite_empty(connection: Connection) -> bool:
    attached = connection.exec_driver_sql("PRAGMA database_list").all()
    if any(row[1] not in {"main", "temp"} for row in attached):
        return False
    for catalog in ("main.sqlite_master", "temp.sqlite_master"):
        if connection.exec_driver_sql(f"SELECT 1 FROM {catalog} LIMIT 1").first() is not None:
            return False
    return True


def _postgres_empty(connection: Connection) -> bool:
    """Inspect all user namespaces, including type/function-only databases."""
    nonempty = connection.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_namespace "
            "WHERE nspname !~ '^pg_' AND nspname NOT IN ('public', 'information_schema')) "
            "OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema') "
            "OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema') "
            "OR EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
            "WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema')"
        )
    ).scalar_one()
    return nonempty is False


def _current_heads(connection: Connection) -> tuple[str, ...]:
    if connection.dialect.name == "sqlite":
        exists = connection.exec_driver_sql(
            "SELECT 1 FROM main.sqlite_master WHERE type='table' AND name='alembic_version'"
        ).first()
        table = "main.alembic_version"
    else:
        exists = connection.execute(
            text(
                "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relname='alembic_version' AND c.relkind='r'"
            )
        ).scalar()
        table = "public.alembic_version"
    if exists is None:
        return ()
    return tuple(
        str(row[0]) for row in connection.exec_driver_sql(f"SELECT version_num FROM {table}")
    )


def assert_online_admission(
    connection: Connection,
    destination: str | tuple[str, ...] | None,
    source_head: str | None,
    source_revisions: frozenset[str],
    baseline: BaselineProof,
) -> None:
    """Allow empty bootstrap, pinned baseline forward paths and verified current-head no-ops."""
    if source_head != BOOTSTRAP_HEAD:
        raise MigrationAdmissionError("DENIED_SOURCE_HISTORY_UNPROVEN")
    if not isinstance(destination, str) or destination not in source_revisions:
        raise MigrationAdmissionError("DENIED_MIGRATION_TARGET_UNPROVEN")
    if connection.dialect.name == "postgresql":
        schema = connection.execute(text("SELECT current_schema()")).scalar_one()
        if schema != "public":
            raise MigrationAdmissionError("DENIED_DATABASE_NAMESPACE_UNPROVEN")
        empty = _postgres_empty(connection)
    elif connection.dialect.name == "sqlite":
        empty = _sqlite_empty(connection)
    else:
        raise MigrationAdmissionError("DENIED_DATABASE_DIALECT_UNPROVEN")
    if empty:
        return
    current = _current_heads(connection)
    if proven_baseline_forward(current, destination, baseline.chain):
        return
    if destination == BOOTSTRAP_HEAD and current == (BOOTSTRAP_HEAD,):
        try:
            require_guards(connection)
        except RuntimeError as exc:
            raise MigrationAdmissionError("DENIED_CURRENT_STATE_UNPROVEN") from exc
        return
    raise MigrationAdmissionError("DENIED_RETIREMENT_UNPROVEN")


def deny_offline_migration() -> None:
    raise MigrationAdmissionError("DENIED_DATABASE_OBSERVATION_REQUIRED")
