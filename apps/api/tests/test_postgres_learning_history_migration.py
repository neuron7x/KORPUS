"""Actual-PostgreSQL legacy refusal controls, independent of bootstrap acceptance."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from korpus.infrastructure.migration_admission import MigrationAdmissionError
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from apps.api.tests.test_postgres_migration_admission import (
    admission_database as admission_database,
)

pytestmark = pytest.mark.postgres
PREVIOUS = "0025_sealed_provenance_integrity"
MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations/versions/0026_learning_history_integrity.py"
)


def test_postgres_learning_previous_head_refuses_populated_upgrade(
    admission_database: tuple[URL, Config],
) -> None:
    url, config = admission_database
    command.upgrade(config, PREVIOUS)
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE learning_legacy_sentinel(value TEXT)")
            connection.exec_driver_sql("INSERT INTO learning_legacy_sentinel VALUES ('preserve')")
        with pytest.raises(MigrationAdmissionError, match="DENIED_RETIREMENT_UNPROVEN"):
            command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").all() == [
                (PREVIOUS,)
            ]
            assert connection.exec_driver_sql(
                "SELECT value FROM learning_legacy_sentinel"
            ).all() == [("preserve",)]
    finally:
        engine.dispose()


def test_postgres_learning_history_preflight_refuses_orphaned_lifecycle(
    admission_database: tuple[URL, Config],
) -> None:
    """Probe the migration preflight, without granting a populated upgrade admission."""
    url, config = admission_database
    command.upgrade(config, PREVIOUS)
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO learning_courses(id, specialty_id, title, created_at) "
                "VALUES ('library', 'public', 'Library course', CURRENT_TIMESTAMP)"
            )
            connection.exec_driver_sql(
                "INSERT INTO learning_course_versions(id, course_id, revision, created_at) "
                "VALUES ('library-v1', 'library', '1', CURRENT_TIMESTAMP)"
            )
        spec = importlib.util.spec_from_file_location("learning_postgres_migration", MIGRATION)
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with (
            pytest.raises(RuntimeError, match="LEARNING_HISTORY_REQUIRES_RECONCILIATION"),
            engine.begin() as connection,
            Operations.context(MigrationContext.configure(connection)),
        ):
            migration.upgrade()
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").all() == [
                (PREVIOUS,)
            ]
            assert connection.exec_driver_sql("SELECT id FROM learning_course_versions").all() == [
                ("library-v1",)
            ]
            assert (
                connection.exec_driver_sql(
                    "SELECT course_version_id FROM learning_publications"
                ).all()
                == []
            )
    finally:
        engine.dispose()
