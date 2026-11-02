from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "run_postgres_security_gate", ROOT / "scripts/run_postgres_security_gate.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PROCESS_GLOBALS = MODULE.process_runtime.__globals__


def test_runtime_binds_shell_suite_to_the_current_interpreter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(root, command, timeout, *, environment=None):
        captured.update(root=root, command=command, timeout=timeout, environment=environment)
        return subprocess.CompletedProcess(command, 0, "passed", "alembic noise")

    monkeypatch.setenv("KORPUS_TEST_DATABASE_URL", "postgresql://available")
    for name in (
        "KORPUS_TEST_DATABASE_ADMIN_URL",
        "KORPUS_POSTGRES_TEST_URL",
        "KORPUS_AUTHZ_DATABASE_URL",
        "KORPUS_REVIEW_DATABASE_URL",
    ):
        monkeypatch.setenv(name, "postgresql://role-fixture/never-connected")
    monkeypatch.setitem(PROCESS_GLOBALS, "run", fake_run)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)

    available, exit_code, tail = MODULE.process_runtime(ROOT, MODULE.TARGETS, True)

    assert available is True
    assert exit_code == 0
    # Хвіст більше не є склейкою двох труб: причина відмови приходить у stdout, а
    # stderr топить її журналом міграцій. Обидві мусять доїхати ПІДПИСАНИМИ — доти цей
    # тест закріплював саме ту форму, яка причину й губила.
    assert "passed" in tail
    assert "alembic noise" in tail
    assert tail.index("passed") < tail.index("alembic noise")
    assert captured["environment"] == {
        "PYTHON": sys.executable,
        "PYTEST_ADDOPTS": " --junitxml=var/postgres-security/pytest-junit.xml",
    }


def test_run_helper_merges_overrides_without_losing_process_environment(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("KORPUS_SENTINEL", "preserved")
    code = (
        "import json, os; print(json.dumps({name: os.environ[name] "
        "for name in ('KORPUS_SENTINEL', 'PYTHON', 'PYTHONPATH')}))"
    )
    completed = MODULE.process_run(
        tmp_path, [sys.executable, "-c", code], 3, environment={"PYTHON": sys.executable}
    )
    assert completed.returncode == 0, completed.stderr
    environment = json.loads(completed.stdout)
    assert environment["KORPUS_SENTINEL"] == "preserved"
    assert environment["PYTHON"] == sys.executable
    assert environment["PYTHONPATH"] == str(tmp_path / "apps/api/src")
