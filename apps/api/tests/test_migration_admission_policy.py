from __future__ import annotations

import ast
import shutil
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from korpus.infrastructure.migration_admission import MigrationAdmissionError
from korpus.infrastructure.migration_baseline_proof import BaselineProofError

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "apps/api"
BASE = "0024_capability_effect_ledger"
HEAD = "0025_sealed_provenance_integrity"


def _configuration(tmp_path: Path) -> tuple[Path, Config]:
    root = tmp_path / "source"
    migrations = root / "apps/api/migrations"
    shutil.copytree(API / "migrations", migrations)
    policy = root / "config/production/migration-policy.json"
    policy.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "config/production/migration-policy.json", policy)
    config = Config(str(API / "alembic.ini"))
    config.set_main_option("script_location", str(migrations))
    return root, config


def _dump(database: Path) -> str:
    with sqlite3.connect(database) as connection:
        return "\n".join(connection.iterdump())


def test_immutable_baseline_forward_path_preserves_existing_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, config = _configuration(tmp_path)
    database = tmp_path / "historical.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    command.upgrade(config, "0023_evidence_search_vector")
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE existing_sentinel(value TEXT)")
        connection.execute("INSERT INTO existing_sentinel VALUES ('keep')")
    command.upgrade(config, BASE)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [(BASE,)]
        assert connection.execute("SELECT value FROM existing_sentinel").fetchall() == [("keep",)]
    before = _dump(database)
    with pytest.raises(MigrationAdmissionError, match="DENIED_RETIREMENT_UNPROVEN"):
        command.upgrade(config, HEAD)
    assert _dump(database) == before


@pytest.mark.parametrize("mutation", ["changed", "missing-policy", "symlink"])
def test_baseline_proof_cannot_be_missing_changed_or_redirected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    root, config = _configuration(tmp_path)
    database = tmp_path / "historical.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    command.upgrade(config, "0023_evidence_search_vector")
    target = root / "apps/api/migrations/versions/0024_capability_effect_ledger.py"
    if mutation == "changed":
        target.write_text(
            target.read_text() + "\nraise AssertionError('mutated source executed before proof')\n"
        )
    elif mutation == "missing-policy":
        (root / "config/production/migration-policy.json").unlink()
    else:
        original = tmp_path / "external.py"
        target.rename(original)
        target.symlink_to(original)
    before = _dump(database)
    with pytest.raises(BaselineProofError, match="DENIED_BASELINE_"):
        command.upgrade(config, BASE)
    assert _dump(database) == before


def test_unknown_future_revision_has_no_implicit_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _configuration(tmp_path)
    database = tmp_path / "future.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    future = root / "apps/api/migrations/versions/0026_unknown.py"
    future.write_text(
        "revision = '0026_unknown'\n"
        f"down_revision = '{HEAD}'\n"
        "def upgrade():\n    raise RuntimeError('untrusted migration executed')\n"
    )
    with pytest.raises(MigrationAdmissionError, match="DENIED_SOURCE_HISTORY_UNPROVEN"):
        command.upgrade(config, "head")
    assert _dump(database) == "BEGIN TRANSACTION;\nCOMMIT;"


def test_removed_runtime_admission_is_detected_by_actual_contract_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _configuration(tmp_path)
    database = tmp_path / "mutant.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    command.upgrade(config, BASE)
    with pytest.raises(MigrationAdmissionError, match="DENIED_RETIREMENT_UNPROVEN"):
        command.upgrade(config, HEAD)
    env = root / "apps/api/migrations/env.py"
    source = env.read_text()
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "assert_online_admission"
    ]
    assert len(calls) == 1
    call = calls[0]
    assert call.end_lineno is not None
    lines = source.splitlines(keepends=True)
    lines[call.lineno - 1 : call.end_lineno] = [" " * call.col_offset + "None\n"]
    env.write_text("".join(lines))
    command.upgrade(config, HEAD)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [(HEAD,)]


def test_failed_bootstrap_rolls_back_all_schema_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _configuration(tmp_path)
    database = tmp_path / "failed-bootstrap.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    path = root / f"apps/api/migrations/versions/{HEAD}.py"
    source = path.read_text()
    upgrade = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
    )
    assert upgrade.end_lineno is not None
    lines = source.splitlines(keepends=True)
    lines.insert(upgrade.end_lineno, "    raise RuntimeError('injected bootstrap failure')\n")
    path.write_text("".join(lines))
    with pytest.raises(RuntimeError, match="injected bootstrap failure"):
        command.upgrade(config, "head")
    assert _dump(database) == "BEGIN TRANSACTION;\nCOMMIT;"
