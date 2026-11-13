from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from korpus.infrastructure.migration_admission import MigrationAdmissionError

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "apps/api"
BASELINE = "0024_capability_effect_ledger"
HEAD = "0025_sealed_provenance_integrity"


def _migrate(
    database: Path, *arguments: str, environment: str = "test"
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        KORPUS_DATABASE_URL=f"sqlite:///{database}",
        KORPUS_ENVIRONMENT=environment,
        PYTHONPATH=str(API / "src"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=API,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _dump(database: Path) -> str:
    with sqlite3.connect(database) as connection:
        return "\n".join(connection.iterdump())


def _baseline(database: Path) -> None:
    outcome = _migrate(database, "upgrade", BASELINE)
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE admission_sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO admission_sentinel VALUES ('preserve-me')")


@pytest.mark.parametrize("environment", ["test", "production"])
def test_populated_baseline_upgrade_denied_without_retirement(
    tmp_path: Path, environment: str
) -> None:
    database = tmp_path / "existing.db"
    _baseline(database)
    before = _dump(database)
    outcome = _migrate(database, "upgrade", "head", environment=environment)
    assert outcome.returncode != 0, "contract migration ran without retirement proof"
    assert "DENIED_RETIREMENT_UNPROVEN" in outcome.stderr
    assert _dump(database) == before


def test_empty_bootstrap_and_current_head_noop(tmp_path: Path) -> None:
    database = tmp_path / "fresh.db"
    outcome = _migrate(database, "upgrade", "head")
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)
        triggers = {
            r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        }
    assert {"trg_sealed_document_delete", "trg_sealed_version_provenance_update"} <= triggers
    before = _dump(database)
    outcome = _migrate(database, "upgrade", "head")
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    assert _dump(database) == before


def test_unversioned_nonempty_database_denied(tmp_path: Path) -> None:
    database = tmp_path / "unversioned.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sentinel(value TEXT)")
        connection.execute("INSERT INTO sentinel VALUES ('untouched')")
    before = _dump(database)
    outcome = _migrate(database, "upgrade", "head")
    assert outcome.returncode != 0
    assert "DENIED_RETIREMENT_UNPROVEN" in outcome.stderr
    assert _dump(database) == before


def test_offline_contract_sql_is_denied_without_database_proof(tmp_path: Path) -> None:
    outcome = _migrate(tmp_path / "unused.db", "upgrade", "head", "--sql")
    assert outcome.returncode != 0
    assert "DENIED_DATABASE_OBSERVATION_REQUIRED" in outcome.stderr
    assert "CREATE TABLE" not in outcome.stdout


def test_guard_removing_downgrade_denied(tmp_path: Path) -> None:
    database = tmp_path / "sealed.db"
    outcome = _migrate(database, "upgrade", "head")
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    before = _dump(database)
    outcome = _migrate(database, "downgrade", BASELINE)
    assert outcome.returncode != 0
    assert "DENIED_RETIREMENT_UNPROVEN" in outcome.stderr
    assert _dump(database) == before


def test_concurrent_bootstrap_rechecks_state_under_migration_lock(tmp_path: Path) -> None:
    database = tmp_path / "concurrent.db"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: _migrate(database, "upgrade", "head"), range(2)))
    assert [r.returncode for r in outcomes] == [0, 0], [r.stderr for r in outcomes]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [(HEAD,)]


def test_unknown_database_revision_denied_without_changes(tmp_path: Path) -> None:
    database = tmp_path / "foreign.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version(version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('unknown_revision')")
    before = _dump(database)
    outcome = _migrate(database, "upgrade", "head")
    assert outcome.returncode != 0
    assert "DENIED_RETIREMENT_UNPROVEN" in outcome.stderr
    assert _dump(database) == before


@pytest.mark.parametrize("prepared", [False, True])
def test_stamp_cannot_replace_bootstrap_or_retirement(tmp_path: Path, prepared: bool) -> None:
    database = tmp_path / "stamp.db"
    if prepared:
        _baseline(database)
    before = _dump(database)
    outcome = _migrate(database, "stamp", "head")
    assert outcome.returncode != 0
    assert "DENIED_MIGRATION_TARGET_UNPROVEN" in outcome.stderr
    assert _dump(database) == before


@pytest.mark.parametrize("prepared", [False, True])
def test_programmatic_stamp_has_same_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prepared: bool
) -> None:
    database = tmp_path / "programmatic-stamp.db"
    if prepared:
        _baseline(database)
    before = _dump(database)
    configuration = Config(str(API / "alembic.ini"))
    configuration.set_main_option("script_location", str(API / "migrations"))
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    with pytest.raises(MigrationAdmissionError, match="DENIED_MIGRATION_TARGET_UNPROVEN"):
        command.stamp(configuration, "head")
    assert _dump(database) == before


@pytest.mark.parametrize("state", ["stamp", "missing", "inert"])
def test_current_revision_claim_cannot_replace_real_guards(tmp_path: Path, state: str) -> None:
    database = tmp_path / "forged-head.db"
    if state == "stamp":
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE alembic_version(version_num TEXT NOT NULL)")
            connection.execute("INSERT INTO alembic_version VALUES (?)", (HEAD,))
    else:
        assert _migrate(database, "upgrade", "head").returncode == 0
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TRIGGER trg_sealed_document_delete")
            if state == "inert":
                connection.execute(
                    "CREATE TRIGGER trg_sealed_document_delete BEFORE DELETE ON documents "
                    "BEGIN SELECT 1; END"
                )
    before = _dump(database)
    outcome = _migrate(database, "upgrade", "head")
    assert outcome.returncode != 0
    assert "DENIED_CURRENT_STATE_UNPROVEN" in outcome.stderr
    assert _dump(database) == before


def test_current_inspection_remains_read_only_on_baseline(tmp_path: Path) -> None:
    database = tmp_path / "inspect.db"
    _baseline(database)
    before = _dump(database)
    outcome = _migrate(database, "current")
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    assert BASELINE in outcome.stdout
    assert _dump(database) == before
