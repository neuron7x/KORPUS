"""Bootstrap and legacy-state refusal controls for the forward history guard migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from korpus.infrastructure.migration_admission import MigrationAdmissionError
from sqlalchemy import create_engine

from apps.api.tests.test_migration_admission_policy import _configuration, _dump

PREVIOUS = "0025_sealed_provenance_integrity"
REVISION = "0026_learning_history_integrity"
MIGRATION = Path(__file__).resolve().parents[1] / f"migrations/versions/{REVISION}.py"


def test_learning_history_populated_previous_head_does_not_acquire_upgrade_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, config = _configuration(tmp_path)
    database = tmp_path / "existing.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    command.upgrade(config, PREVIOUS)
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE existing_sentinel(value TEXT)")
            connection.exec_driver_sql("INSERT INTO existing_sentinel VALUES ('preserve')")
        before = _dump(database)
        with pytest.raises(MigrationAdmissionError, match="DENIED_RETIREMENT_UNPROVEN"):
            command.upgrade(config, "head")
        assert _dump(database) == before
    finally:
        engine.dispose()


def test_learning_history_migration_refuses_missing_publication_without_reconstructing_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execute the preflight itself; this direct test is not admission for a live upgrade."""
    _, config = _configuration(tmp_path)
    database = tmp_path / "orphaned-history.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    command.upgrade(config, PREVIOUS)
    engine = create_engine(f"sqlite:///{database}")
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
        before = _dump(database)
        spec = importlib.util.spec_from_file_location(
            "korpus_learning_history_migration", MIGRATION
        )
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with (
            pytest.raises(RuntimeError, match="LEARNING_HISTORY_REQUIRES_RECONCILIATION"),
            engine.begin() as connection,
            Operations.context(MigrationContext.configure(connection)),
        ):
            migration.upgrade()
        assert _dump(database) == before
    finally:
        engine.dispose()
