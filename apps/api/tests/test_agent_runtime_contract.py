from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/run_isolated_routine.py"
SPEC = importlib.util.spec_from_file_location("run_isolated_routine", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

INSTALL_SCRIPT = ROOT / "scripts/install_agent_runtime.py"
INSTALL_SPEC = importlib.util.spec_from_file_location("install_agent_runtime", INSTALL_SCRIPT)
assert INSTALL_SPEC is not None and INSTALL_SPEC.loader is not None
INSTALLER = importlib.util.module_from_spec(INSTALL_SPEC)
INSTALL_SPEC.loader.exec_module(INSTALLER)


def _clean_repository(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "--quiet", "--initial-branch=main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@korpus.local"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "KORPUS test"], cwd=path, check=True)
    (path / "tracked.txt").write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "fixture"], cwd=path, check=True)
    return path


def test_repository_lease_refuses_a_second_routine() -> None:
    with (
        MODULE.repository_lease(ROOT),
        pytest.raises(MODULE.RepositoryBusy, match="repository lease is held"),
        MODULE.repository_lease(ROOT),
    ):
        pass


def test_agent_executes_only_in_a_clean_disposable_worktree(tmp_path: Path) -> None:
    repository = _clean_repository(tmp_path / "repository")
    state = tmp_path / "state"
    code = (
        "from pathlib import Path; import subprocess; print(Path.cwd()); "
        "print('venv=' + str(Path('apps/api/.venv').is_symlink())); "
        "print('dirty=' + str(bool(subprocess.check_output(['git','status','--porcelain']).strip())))"
    )

    result = MODULE.run_isolated(
        repository=repository,
        name="isolation-proof",
        command=[sys.executable, "-c", code],
        timeout_seconds=30,
        state_dir=state,
    )

    assert result == 0
    receipt = json.loads((state / "isolation-proof.json").read_text(encoding="utf-8"))
    log = Path(receipt["log"]).read_text(encoding="utf-8")
    assert str(repository) not in log
    assert "dirty=False" in log
    assert receipt["return_code"] == 0


def test_dirty_source_tree_is_refused_before_agent_execution(tmp_path: Path) -> None:
    repository = _clean_repository(tmp_path / "repository")
    (repository / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    state = tmp_path / "state"

    result = MODULE.run_isolated(
        repository=repository,
        name="dirty-refusal",
        command=[sys.executable, "-c", "raise SystemExit('must not execute')"],
        timeout_seconds=30,
        state_dir=state,
    )

    receipt = json.loads((state / "dirty-refusal.json").read_text(encoding="utf-8"))
    assert result == MODULE.DIRTY_EXIT
    assert receipt["return_code"] == MODULE.DIRTY_EXIT
    assert "source repository is dirty" in receipt["reason"]
    assert not Path(receipt["log"]).exists()


def test_existing_locked_interpreter_is_reused_without_copying(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    worktree = tmp_path / "worktree"
    source = repository / "apps/api/.venv"
    source.mkdir(parents=True)
    (worktree / "apps/api").mkdir(parents=True)

    MODULE._provision_interpreter(repository, worktree)

    destination = worktree / "apps/api/.venv"
    assert destination.is_symlink()
    assert destination.resolve() == source.resolve()


def test_timeout_terminates_the_agent_process_group(tmp_path: Path) -> None:
    child_pid = tmp_path / "child.pid"
    marker = tmp_path / "escaped.marker"
    command = [
        sys.executable,
        "-c",
        (
            "import pathlib, subprocess, time; "
            "child=subprocess.Popen(["
            f"{sys.executable!r},'-c',\"import pathlib,time; time.sleep(2); pathlib.Path({str(marker)!r}).write_text('escaped')\""
            "], start_new_session=True); "
            f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid)); "
            "time.sleep(30)"
        ),
    ]
    with (tmp_path / "timeout.log").open("wb") as log:
        result = MODULE._run_bounded(command, tmp_path, log, 1)

    assert result == MODULE.TIMEOUT_EXIT
    pid = int(child_pid.read_text(encoding="utf-8"))
    for _ in range(20):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"timed-out descendant survived: pid={pid}")
    time.sleep(2)
    assert not marker.exists()


def test_normal_agent_exit_cannot_leave_a_detached_descendant(tmp_path: Path) -> None:
    marker = tmp_path / "escaped.marker"
    command = [
        sys.executable,
        "-c",
        (
            "import subprocess; subprocess.Popen(["
            f"{sys.executable!r},'-c',\"import pathlib,time; time.sleep(1); pathlib.Path({str(marker)!r}).write_text('escaped')\""
            "], start_new_session=True)"
        ),
    ]
    with (tmp_path / "normal.log").open("wb") as log:
        result = MODULE._run_bounded(command, tmp_path, log, 10)

    assert result == 0
    time.sleep(1)
    assert not marker.exists()


def test_mutation_concurrency_is_bounded_locally_and_explicit_in_ci() -> None:
    runner = (ROOT / "scripts/run_mutation_shards.sh").read_text(encoding="utf-8")
    pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")

    assert "KORPUS_MUTATION_SHARDS:-6" in runner
    assert "KORPUS_MUTATION_JOBS:-1" in runner
    assert "KORPUS_MUTATION_SHARDS=6 KORPUS_MUTATION_JOBS=2" in pipeline


def test_every_timer_uses_the_isolated_bounded_runner() -> None:
    unit = INSTALLER.render()

    assert "@KORPUS_ROOT@" not in unit
    assert "scripts/run_isolated_routine.py" in unit
    assert "--name %i" in unit
    assert "--prompt-file %h/.claude/routines/%i.prompt" in unit
    assert "KillMode=control-group" in unit
    assert "CPUQuota=300%" in unit
    assert "MemoryHigh=3G" in unit
    assert "MemoryMax=5G" in unit
