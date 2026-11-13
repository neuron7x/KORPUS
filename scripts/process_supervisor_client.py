"""Transport to a dedicated subreaper; failed supervision cannot report success."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from process_supervisor_capture import OUTPUT_LIMIT_BYTES

BoundedResult = tuple[int | None, str, str, bool, str]


def _receipt(value: Any) -> BoundedResult:
    if not isinstance(value, dict) or not isinstance(value.get("termination"), str):
        return None, "", "", False, "supervisor_invalid_receipt"
    code, clean = value.get("returncode"), value.get("children_reaped")
    if clean is not True or (code is not None and type(code) is not int):
        return None, "", "", False, value["termination"] + ":cleanup_unproven"
    stdout, stderr = value.get("stdout"), value.get("stderr")
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        return None, "", "", False, "supervisor_invalid_receipt"
    if max(len(stdout), len(stderr)) > OUTPUT_LIMIT_BYTES:
        return None, "", "", False, "supervisor_invalid_receipt"
    if code is not None and (
        value["termination"] != "not_required" or value.get("timed_out") is not False
    ):
        return None, "", "", False, "supervisor_invalid_receipt"
    return code, stdout, stderr, value.get("timed_out") is True, value["termination"]


def _cancel(process: subprocess.Popen[str]) -> str:
    process.terminate()  # Only our unreaped supervisor; it performs descendant cleanup.
    try:
        process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            return "supervisor_unreaped:cleanup_unproven"
    return "supervisor_interrupted:cleanup_unproven"


def _communicate(process: subprocess.Popen[str], request: str, timeout: float) -> BoundedResult:
    try:
        stdout, _stderr = process.communicate(request, timeout=timeout + 5)
    except subprocess.TimeoutExpired:
        return None, "", "", False, _cancel(process)
    except (KeyboardInterrupt, SystemExit):
        _cancel(process)
        raise
    if process.returncode != 0:
        return None, "", "", False, "supervisor_failed:cleanup_unproven"
    try:
        return _receipt(json.loads(stdout))
    except (ValueError, TypeError):
        return None, "", "", False, "supervisor_invalid_receipt"


def supervise(
    cmd: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: float,
) -> BoundedResult:
    if sys.platform != "linux":
        return None, "", "", False, "unsupported_child_ownership"
    supervisor = Path(__file__).with_name("process_tree_supervisor.py")
    request = json.dumps(
        {"cmd": list(cmd), "cwd": str(cwd), "env": dict(env), "timeout": timeout_seconds}
    )
    try:
        process = subprocess.Popen(
            [sys.executable, "-B", "-I", str(supervisor)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        try:
            return _communicate(process, request, timeout_seconds)
        finally:
            if process.stdin is not None:
                process.stdin.close()
            if process.stdout is not None:
                process.stdout.close()
    except OSError:
        return None, "", "", False, "supervisor_unavailable"
