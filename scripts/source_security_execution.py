"""Bound native executions and prove owned container removal before recording exit."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.source_security_container import cleanup, cleanup_valid, owned_command


def environment() -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"}


def execution_succeeded(execution: dict[str, Any]) -> bool:
    return (
        type(execution.get("exit_code")) is int
        and execution["exit_code"] == 0
        and cleanup_valid(execution)
    )


def _run(command: list[str], cwd: Path, log: Any) -> int:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=environment(),
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=240,
            check=False,
        ).returncode
    except subprocess.TimeoutExpired:
        log.write(b"\nSOURCE_SECURITY_TIMEOUT\n")
        return 124
    except OSError:
        log.write(b"\nSOURCE_SECURITY_EXECUTION_UNAVAILABLE\n")
        return 127


def execute(tool: str, command: list[str], output: Path, cwd: Path) -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    actual, owned = owned_command(tool, command)
    record: dict[str, Any] = {"tool": tool, "command": actual, "started_at": started}
    with (output / f"{tool.replace(':', '-')}.log").open("wb") as log:
        try:
            code = _run(actual, cwd, log)
        finally:
            if owned is not None:
                record["cleanup"] = cleanup(owned, environment())
        if not cleanup_valid(record):
            log.write(b"\nSOURCE_SECURITY_CLEANUP_UNPROVEN\n")
            code = code or 125
    record.update(exit_code=code, completed_at=datetime.now(UTC).isoformat())
    return record
