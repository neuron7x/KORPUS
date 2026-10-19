"""Bound PostgreSQL gate subprocesses and retain complete streams on failure.

A timeout is a measured failure (exit 124), so the caller can still write its gate
JSON. Each subprocess owns a process group; killing only its shell would leave
pytest alive with the capture pipes open, defeating the original timeout.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from contextlib import suppress
from pathlib import Path


def terminate_group(process: subprocess.Popen[str]) -> tuple[str, str]:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        return process.communicate(timeout=5)


def invoke(
    root: Path,
    command: list[str],
    timeout: float,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    try:
        with subprocess.Popen(
            command,
            cwd=root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        ) as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                returncode = process.returncode
            except subprocess.TimeoutExpired:
                stdout, stderr = terminate_group(process)
                returncode = 124
                stderr += f"\nPOSTGRES_SUBPROCESS_TIMEOUT: exceeded {timeout} seconds\n"
    except OSError as error:
        return subprocess.CompletedProcess(
            command, 127, "", f"POSTGRES_SUBPROCESS_START_FAILED: {error}\n"
        )
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def run_with_diagnostics(
    root: Path,
    command: list[str],
    timeout: float,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    selected = {**os.environ, "PYTHONPATH": str(root / "apps/api/src"), **(environment or {})}
    phase = "runtime" if "scripts/run_postgres_suite.sh" in command else "static"
    directory = root / "var/postgres-security"
    directory.mkdir(parents=True, exist_ok=True)
    result = invoke(root, command, timeout, selected)
    for stream in ("stdout", "stderr"):
        (directory / f"{phase}-{stream}.log").write_text(getattr(result, stream), encoding="utf-8")
    error_code = (
        "POSTGRES_SUBPROCESS_TIMEOUT" if result.returncode == 124 else "POSTGRES_SUBPROCESS_FAILED"
    )
    (directory / f"{phase}-process.json").write_text(
        json.dumps(
            {
                "schema": "korpus.postgres-gate-process.v1",
                "phase": phase,
                "status": "PASS" if result.returncode == 0 else "FAIL",
                "error_code": None if result.returncode == 0 else error_code,
                "command": command,
                "exit_code": result.returncode,
                "timeout_seconds": timeout,
                "stdout_log": f"var/postgres-security/{phase}-stdout.log",
                "stderr_log": f"var/postgres-security/{phase}-stderr.log",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result
