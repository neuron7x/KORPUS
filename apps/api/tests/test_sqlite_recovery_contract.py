from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from korpus.config import OPERATIONAL_VARIABLES

ROOT = Path(__file__).resolve().parents[3]


def test_sqlite_recovery_environment_names_are_declared_operational_variables() -> None:
    required = {
        "KORPUS_BACKUP_SQLITE_PATH",
        "KORPUS_BACKUP_OBJECT_ROOT",
        "KORPUS_BACKUP_SECOND_DIR",
        "KORPUS_BACKUP_RETENTION_COUNT",
        "KORPUS_BACKUP_RETENTION_DAYS",
        "KORPUS_RECOVERY_ENVIRONMENT_CLASS",
    }
    assert required <= OPERATIONAL_VARIABLES


def test_sqlite_recovery_drill_is_fail_honest_about_fixture_class() -> None:
    text = (ROOT / "scripts/run_sqlite_recovery_drill.sh").read_text(encoding="utf-8")
    assert 'KORPUS_RECOVERY_ENVIRONMENT_CLASS="CI_FIXTURE"' in text
    assert "scripts/backup_sqlite.sh" in text
    assert "scripts/restore_sqlite.sh" in text
    assert "scripts/measure_recovery.py" in text
    assert "KORPUS_RECOVERY_PHASE=after-backup" in text


@pytest.mark.parametrize(
    "selection",
    ["absolute", "relative", "path-name", "relative-path-entry", "current-directory-path-entry"],
)
def test_sqlite_recovery_drill_resolves_interpreter_across_chdir(
    tmp_path: Path, selection: str
) -> None:
    root = tmp_path / "checkout with spaces"
    (root / "scripts").mkdir(parents=True)
    (root / "apps/api").mkdir(parents=True)
    (root / "bin").mkdir()
    script = root / "scripts/run_sqlite_recovery_drill.sh"
    shutil.copyfile(ROOT / "scripts/run_sqlite_recovery_drill.sh", script)
    interpreter = root / (
        "probe-python" if selection == "current-directory-path-entry" else "bin/probe-python"
    )
    interpreter.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$PWD" >> "$PROBE_LOG"\n'
        'if [[ "$1" == "-c" ]]; then printf "%064d\\n" 0 > "$3"; exit 0; fi\n'
        "exit 73\n"
    )
    interpreter.chmod(0o755)
    selected = {
        "absolute": str(interpreter),
        "relative": "bin/probe-python",
        "path-name": "probe-python",
        "relative-path-entry": "probe-python",
        "current-directory-path-entry": "probe-python",
    }[selection]
    path_entry = {"relative-path-entry": "bin", "current-directory-path-entry": ""}.get(
        selection, str(interpreter.parent)
    )
    log = tmp_path / "interpreter-cwd.log"
    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHON": selected,
            "PATH": path_entry + os.pathsep + os.environ["PATH"],
            "PROBE_LOG": str(log),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 73, result.stderr
    assert log.read_text().splitlines() == [str(root), str(root / "apps/api")]


@pytest.mark.parametrize("selection", ["missing-path-name", "directory"])
def test_sqlite_recovery_drill_rejects_invalid_interpreter_before_fixture_reset(
    tmp_path: Path, selection: str
) -> None:
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    script = root / "scripts/run_sqlite_recovery_drill.sh"
    shutil.copyfile(ROOT / "scripts/run_sqlite_recovery_drill.sh", script)
    work = root / "var/sqlite-recovery-drill"
    work.mkdir(parents=True)
    marker = work / "preserved.txt"
    marker.write_text("preserve existing fixture until interpreter is admitted")
    result = subprocess.run(
        ["/bin/bash", str(script)],
        env={
            **os.environ,
            "PYTHON": str(root) if selection == "directory" else "no-such-korpus-python",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 69
    assert "Python interpreter is not executable" in result.stderr
    assert marker.is_file()


def test_recovery_measurement_uses_latest_protected_write_not_audit_only() -> None:
    text = (ROOT / "scripts/measure_recovery.py").read_text(encoding="utf-8")
    assert "def _latest_protected_write" in text
    assert "max(created_at)" in text and "FROM documents" in text
    assert "max(occurred_at)" in text and "FROM audit_events" in text
    assert "rpo_seconds = _interval(newest, newest_restored)" in text
