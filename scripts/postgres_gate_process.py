from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def run(
    root: Path,
    command: list[str],
    timeout: int,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    selected = {**os.environ, "PYTHONPATH": str(root / "apps/api/src")}
    if environment:
        selected.update(environment)
    return subprocess.run(
        command,
        cwd=root,
        env=selected,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def runtime(root: Path, targets: list[str], targets_present: bool) -> tuple[bool, int | None, str]:
    available = bool(os.getenv("KORPUS_TEST_DATABASE_URL")) or shutil.which("docker") is not None
    if not targets_present or not available:
        return available, None, ""
    completed = run(
        root,
        ["bash", "scripts/run_postgres_suite.sh", *targets],
        600,
        environment={"PYTHON": sys.executable},
    )
    return available, completed.returncode, (completed.stdout + completed.stderr)[-8000:]
