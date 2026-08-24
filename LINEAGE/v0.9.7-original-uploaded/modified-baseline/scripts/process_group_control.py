#!/usr/bin/env python3
"""POSIX-aware subprocess-tree termination used by bounded harnesses."""
from __future__ import annotations

import os
import signal
import subprocess
import time


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def terminate_process_tree(process: subprocess.Popen[str], grace_seconds: float = 2.0) -> str:
    if os.name != "posix":
        if process.poll() is not None:
            return "already_exited"
        process.terminate()
        try:
            process.wait(timeout=grace_seconds)
            return "terminate_process"
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=max(grace_seconds, 1.0))
            return "kill_process"
    pgid = process.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return "process_group_absent"
    deadline = time.monotonic() + grace_seconds
    while _group_alive(pgid) and time.monotonic() < deadline:
        time.sleep(0.02)
    termination = "sigterm_process_group"
    if _group_alive(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError: termination = "process_group_absent_after_sigterm"
        else:
            termination = "sigkill_process_group"
    try:
        process.wait(timeout=max(grace_seconds, 1.0))
    except subprocess.TimeoutExpired:
        process.kill(); process.wait(timeout=max(grace_seconds, 1.0))
    return termination
