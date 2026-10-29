"""Exercise shell selection/readiness and real bounded subprocess failures.

Docker and pytest are recording executables in the shell tests; those tests make
no database claim. The security gate still runs its unchanged nine real targets
against PostgreSQL in CI, in addition to the mandatory full coverage suite.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import postgres_gate_process as process  # noqa: E402
import run_postgres_security_gate as gate  # noqa: E402
from postgres_process_diagnostics import run_with_diagnostics  # noqa: E402


def _executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def shell_root(tmp_path: Path) -> Path:
    for directory in ("scripts", "apps/api/tests", "var", "bin"):
        (tmp_path / directory).mkdir(parents=True)
    for name in ("run_postgres_suite.sh", "run_postgres_coverage.sh"):
        shutil.copyfile(ROOT / "scripts" / name, tmp_path / "scripts" / name)
    for name in ("test_one.py", "test_two.py"):
        (tmp_path / "apps/api/tests" / name).write_text("# shell-selection fixture\n")
    _executable(
        tmp_path / "bin/record-python",
        f"#!{sys.executable}\n" + "import json, sys\nfrom pathlib import Path\n"
        'with (Path(__file__).resolve().parents[1] / "var/commands.jsonl").open("a") as out:\n'
        '    out.write(json.dumps(sys.argv[1:]) + "\\n")\n',
    )
    _executable(
        tmp_path / "bin/docker",
        f"#!{sys.executable}\n" + "import json, os, sys\nfrom pathlib import Path\n"
        'if "pg_isready" in sys.argv:\n'
        '    counter = Path("var/readiness-count")\n'
        "    index = int(counter.read_text()) if counter.exists() else 0\n"
        "    counter.write_text(str(index + 1))\n"
        '    if "-h" not in sys.argv or sys.argv[sys.argv.index("-h") + 1] != "127.0.0.1":\n'
        "        sys.exit(0)  # the temporary socket server is already accepting\n"
        '    states = json.loads(os.environ["PG_FIXTURE_READINESS"])\n'
        "    sys.exit(states[index % len(states)])\n"
        'if sys.argv[1] == "logs":\n'
        '    print("fixture PostgreSQL init restart diagnostics")\n',
    )
    _executable(tmp_path / "bin/sleep", "#!/bin/sh\nexit 0\n")
    return tmp_path


def _shell(
    root: Path, script: str, args: list[str], *, database: bool, states: list[int] | None = None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("KORPUS_TEST_DATABASE_URL", None)
    environment.pop("KORPUS_PG_KEEP", None)
    environment.update(
        {
            "PYTHON": str(root / "bin/record-python"),
            "PATH": str(root / "bin") + os.pathsep + environment["PATH"],
            "PG_FIXTURE_READINESS": json.dumps(states or [0]),
        }
    )
    if database:
        environment["KORPUS_TEST_DATABASE_URL"] = "postgresql://shell-fixture/never-connected"
    return subprocess.run(
        ["bash", "scripts/" + script, *args],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )


def _commands(root: Path) -> list[list[str]]:
    path = root / "var/commands.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


@pytest.mark.parametrize("database", [False, True])
@pytest.mark.parametrize("targeted", [False, True])
def test_full_suite_is_default_and_selected_files_require_explicit_mode(
    shell_root: Path, database: bool, targeted: bool
) -> None:
    selected = ["apps/api/tests/test_one.py", "apps/api/tests/test_two.py"]
    args = ["--targeted", *selected] if targeted else ["-q"]
    result = _shell(shell_root, "run_postgres_suite.sh", args, database=database)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [call for call in _commands(shell_root) if "pytest" in call]
    assert len(calls) == 1
    assert "--no-cov" in calls[0]
    assert ("apps/api/tests" in calls[0]) is not targeted
    assert [argument for argument in calls[0] if argument.endswith(".py")] == (
        selected if targeted else []
    )
    if not targeted:
        assert "-q" in calls[0]


@pytest.mark.parametrize(
    "args",
    [
        ["--targeted"],
        ["--targeted", "apps/api/tests/missing.py"],
        ["--targeted", "apps/api/tests/../wrong.py"],
    ],
)
def test_empty_or_invalid_targeted_selection_fails_before_execution(
    shell_root: Path, args: list[str]
) -> None:
    result = _shell(shell_root, "run_postgres_suite.sh", args, database=True)
    assert result.returncode == 2
    assert not _commands(shell_root)


@pytest.mark.parametrize("script", ["run_postgres_suite.sh", "run_postgres_coverage.sh"])
def test_readiness_ignores_temporary_server_and_waits_for_three_stable_successes(
    shell_root: Path, script: str
) -> None:
    result = _shell(shell_root, script, [], database=False, states=[0, 1, 0, 0, 0])
    assert result.returncode == 0, result.stdout + result.stderr
    assert (shell_root / "var/readiness-count").read_text() == "5"
    assert _commands(shell_root)


@pytest.mark.parametrize("script", ["run_postgres_suite.sh", "run_postgres_coverage.sh"])
def test_unstable_database_fails_and_keeps_initialization_diagnostics(
    shell_root: Path, script: str
) -> None:
    result = _shell(shell_root, script, [], database=False, states=[0, 1])
    assert result.returncode == 69
    assert (shell_root / "var/readiness-count").read_text() == "60"
    assert "fixture PostgreSQL init restart diagnostics" in result.stderr
    assert not _commands(shell_root)


def test_security_runtime_selects_its_actual_complete_target_list(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("KORPUS_TEST_DATABASE_URL", "postgresql://command-fixture/never-connected")

    def record(root, command, timeout, *, environment=None):
        calls.append((command, timeout, environment))
        return subprocess.CompletedProcess(command, 0, "selected suite", "")

    monkeypatch.setattr(process, "run", record)
    assert process.runtime(ROOT, gate.TARGETS, True)[1] == 0
    assert calls[0][0] == ["bash", "scripts/run_postgres_suite.sh", "--targeted", *gate.TARGETS]
    assert len(gate.TARGETS) == 10
    assert calls[0][1] == 600


def test_real_timeout_kills_descendants_and_preserves_both_streams(tmp_path: Path) -> None:
    code = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(6)']); "
        "print('cause before timeout', flush=True); "
        "print('stderr before timeout', file=sys.stderr, flush=True); time.sleep(20)"
    )
    started = time.monotonic()
    result = run_with_diagnostics(tmp_path, [sys.executable, "-c", code], 1)
    assert time.monotonic() - started < 5
    assert result.returncode == 124
    assert "cause before timeout" in result.stdout
    assert "stderr before timeout" in result.stderr
    receipt = json.loads((tmp_path / "var/postgres-security/static-process.json").read_text())
    assert receipt["status"] == "FAIL"
    assert receipt["error_code"] == "POSTGRES_SUBPROCESS_TIMEOUT"
    assert receipt["exit_code"] == 124
    assert (tmp_path / receipt["stdout_log"]).read_text() == result.stdout
    assert (tmp_path / receipt["stderr_log"]).read_text() == result.stderr


def test_timed_out_runtime_still_writes_the_security_failure_json(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/run_postgres_suite.sh").write_text(
        '#!/bin/bash\nprintf "runtime cause\\n"\nprintf "runtime error\\n" >&2\nsleep 6\n',
        encoding="utf-8",
    )
    for relative in gate.TARGETS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# gate timeout fixture; never a PostgreSQL measurement\n")
    monkeypatch.setenv("KORPUS_TEST_DATABASE_URL", "postgresql://timeout-fixture/never-connected")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "compute_source_digest", lambda _: "a" * 64)
    monkeypatch.setattr(
        gate, "process_run", lambda *args: subprocess.CompletedProcess([], 0, "static fixture", "")
    )

    def bounded(root, command, timeout, *, environment=None):
        return run_with_diagnostics(root, command, 0.25, environment=environment)

    monkeypatch.setattr(process, "run", bounded)
    assert gate.main() == 1
    report = json.loads((tmp_path / "var/production/postgres_security-gate.json").read_text())
    assert report["status"] == "FAIL"
    assert report["runtime_exit_code"] == 124
    assert "postgres_adversarial_suite" in report["failures"]
    assert "POSTGRES_SUBPROCESS_TIMEOUT" in report["runtime_tail"]
    assert "runtime cause" in report["runtime_tail"]
    assert "runtime error" in report["runtime_tail"]
