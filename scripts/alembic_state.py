#!/usr/bin/env python3
"""Derive and verify migration state from Alembic's authoritative graph."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = ROOT / "apps/api/alembic.ini"


class MigrationStateError(RuntimeError):
    """A fail-closed migration graph or database-state mismatch."""


def expected_heads(config_path: Path = ALEMBIC_INI) -> tuple[str, ...]:
    config = Config(str(config_path))
    configured_location = config.get_main_option("script_location")
    if not configured_location:
        raise MigrationStateError("DB-01_MIGRATION_GRAPH: Alembic script_location is missing")
    script_location = Path(configured_location)
    if not script_location.is_absolute():
        script_location = config_path.parent / script_location
    config.set_main_option("script_location", str(script_location.resolve()))
    heads = tuple(sorted(ScriptDirectory.from_config(config).get_heads()))
    if len(heads) != 1:
        raise MigrationStateError(
            f"DB-01_MIGRATION_GRAPH: expected exactly one Alembic head, got {list(heads)}"
        )
    return heads


def verify_revisions(
    actual: Iterable[str], expected: Iterable[str] | None = None
) -> tuple[str, ...]:
    expected_set = tuple(sorted(expected if expected is not None else expected_heads()))
    actual_set = tuple(sorted(actual))
    if not expected_set or actual_set != expected_set:
        raise MigrationStateError(
            f"DB-01_SCHEMA_REVISION: expected {list(expected_set)}, got {list(actual_set)}"
        )
    return actual_set


def database_revisions(database_url: str) -> tuple[str, ...]:
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return tuple(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
            )
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    revisions = verify_revisions(database_revisions(args.database_url))
    print("verified Alembic head: " + ",".join(revisions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
