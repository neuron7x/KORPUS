from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import marshal
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script.base import ScriptDirectory
from alembic.util.exc import CommandError
from korpus.infrastructure import migration_admission
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


_WITNESS = """
def _witness():
    connection = op.get_bind()
    connection.exec_driver_sql("CREATE TABLE admission_import_witness(value TEXT)")
    connection.exec_driver_sql("INSERT INTO admission_import_witness VALUES ('before-admission')")
    connection.commit()
    return lambda function: function
"""


@pytest.mark.parametrize(
    "payload",
    [
        "_witness()",
        "@_witness()\ndef decorated():\n    return None",
        "def with_default(value=_witness()):\n    return None",
        "def annotated() -> _witness():\n    return None",
        "value: _witness() = None",
        "class Executes:\n    _witness()",
        "class WithBase(_witness()):\n    pass",
        "assigned = [_witness() for _ in (1,)]",
        "import admission_witness_dependency",
        "from admission_witness_dependency import marker",
    ],
    ids=[
        "call",
        "decorator",
        "default",
        "return-annotation",
        "annotation",
        "class-body",
        "class-base",
        "comprehension",
        "import",
        "from-import",
    ],
)
def test_revision_initialization_is_denied_before_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    root, config = _configuration(tmp_path)
    database = tmp_path / "source-init.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    command.upgrade(config, BASE)
    dependency = tmp_path / "admission_witness_dependency.py"
    dependency.write_text("from alembic import op\n" + _WITNESS + "\nmarker = _witness()\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    path = root / f"apps/api/migrations/versions/{HEAD}.py"
    source = path.read_text()
    if payload.startswith(("def annotated", "value:")):
        source = source.replace("from __future__ import annotations\n", "")
    path.write_text(source + _WITNESS + "\n" + payload + "\n")
    before, before_bytes = _dump(database), database.read_bytes()
    with pytest.raises(BaselineProofError, match="DENIED_REVISION_INITIALIZATION_UNPROVEN"):
        command.upgrade(config, "head")
    assert _dump(database) == before
    assert database.read_bytes() == before_bytes
    assert "admission_witness_dependency" not in sys.modules


@pytest.mark.parametrize("operation", ["upgrade", "current", "check"])
def test_cli_rejects_import_side_effect_and_preserves_the_same_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    root, config = _configuration(tmp_path)
    database = tmp_path / "cli-source-init.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    command.upgrade(config, BASE)
    ini = root / "apps/api/alembic.ini"
    shutil.copyfile(API / "alembic.ini", ini)
    path = root / f"apps/api/migrations/versions/{HEAD}.py"
    path.write_text(path.read_text() + _WITNESS + "\n_witness()\n")
    before, before_bytes = _dump(database), database.read_bytes()
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ini), operation]
        + (["head"] if operation == "upgrade" else []),
        cwd=root / "apps/api",
        env={**os.environ, "PYTHONPATH": str(API / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "DENIED_REVISION_INITIALIZATION_UNPROVEN" in result.stderr
    assert _dump(database) == before
    assert database.read_bytes() == before_bytes


def test_migration_executes_captured_source_after_admission_not_replaced_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _configuration(tmp_path)
    database = tmp_path / "captured-source.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    path = root / f"apps/api/migrations/versions/{HEAD}.py"
    original = migration_admission.assert_online_admission

    def replace_after_proof(*args: object) -> None:
        original(*args)
        path.write_text(path.read_text() + _WITNESS + "\n_witness()\n")

    monkeypatch.setattr(migration_admission, "assert_online_admission", replace_after_proof)
    command.upgrade(config, "head")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [(HEAD,)]
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name='admission_import_witness'"
            ).fetchall()
            == []
        )
    before = _dump(database)
    with pytest.raises(BaselineProofError, match="DENIED_REVISION_INITIALIZATION_UNPROVEN"):
        command.upgrade(config, "head")
    assert _dump(database) == before


def test_valid_source_cannot_be_replaced_by_cached_bytecode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = _configuration(tmp_path)
    database = tmp_path / "bytecode.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    path = root / f"apps/api/migrations/versions/{HEAD}.py"
    cache = Path(importlib.util.cache_from_source(str(path)))
    cache.parent.mkdir(exist_ok=True)
    source = path.read_text() + _WITNESS + "\n_witness()\n'cached-witness'\n"
    header = importlib.util.MAGIC_NUMBER + struct.pack(
        "<III", 0, int(path.stat().st_mtime), path.stat().st_size
    )
    cache.write_bytes(header + marshal.dumps(compile(source, str(path), "exec")))
    loader = importlib.machinery.SourceFileLoader("cache_control", str(path))
    cached = loader.get_code("cache_control")
    assert cached is not None and "_witness" in cached.co_names
    command.upgrade(config, "head")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [(HEAD,)]
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name='admission_import_witness'"
            ).fetchall()
            == []
        )


def test_contract_denial_precedes_alembic_revision_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, config = _configuration(tmp_path)
    database = tmp_path / "no-import.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    command.upgrade(config, BASE)
    before = _dump(database)

    def forbidden_loader(*args: object) -> None:
        raise AssertionError("Alembic imported revisions before database admission")

    monkeypatch.setattr(ScriptDirectory, "_load_revisions", forbidden_loader)
    with pytest.raises(MigrationAdmissionError, match="DENIED_RETIREMENT_UNPROVEN"):
        command.upgrade(config, "head")
    assert _dump(database) == before


def test_alembic_check_keeps_its_readonly_baseline_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, config = _configuration(tmp_path)
    database = tmp_path / "check.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    command.upgrade(config, BASE)
    before = _dump(database)
    with pytest.raises(CommandError, match="Target database is not up to date"):
        command.check(config)
    assert _dump(database) == before


def test_unknown_callback_cannot_claim_a_canonical_migration_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, config = _configuration(tmp_path)
    database = tmp_path / "unknown-operation.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    script = ScriptDirectory.from_config(config)

    def counterfeit(*args: object) -> None:
        raise AssertionError("unknown callback executed")

    with (
        pytest.raises(MigrationAdmissionError, match="DENIED_OPERATION_UNPROVEN"),
        EnvironmentContext(config, script, fn=counterfeit, destination_rev=HEAD),
    ):
        script.run_env()
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
