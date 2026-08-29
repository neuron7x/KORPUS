#!/usr/bin/env python3
"""Process-tree liveness and file-backed capture for bounded harness execution."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO

from process_group_control import process_group_alive, terminate_process_tree


def _capture_text(handle: IO[str]) -> str:
    handle.flush()
    handle.seek(0)
    return handle.read()


def execute_bounded_process(
    cmd: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout_seconds: float
) -> tuple[int | None, str, str, bool, str]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    with (
        tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as stdout_file,
        tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as stderr_file,
    ):
        # Popen is overloaded on the exact combination of text/encoding arguments, so a
        # dict[str, object] of keyword arguments matches no overload. start_new_session is
        # the one that varies by platform, and it is a bool either way.
        process = subprocess.Popen(
            list(cmd),
            cwd=cwd,
            env=dict(env),
            text=True,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=os.name == "posix",
        )
        timed_out = False
        termination = "not_required"
        if os.name == "posix":
            deadline = time.monotonic() + timeout_seconds
            while process_group_alive(process.pid):
                process.poll()
                if time.monotonic() >= deadline:
                    timed_out = True
                    termination = terminate_process_tree(process)
                    break
                time.sleep(0.02)
            if not timed_out:
                process.wait(timeout=max(timeout_seconds, 1.0))
        else:
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                termination = terminate_process_tree(process)
        stdout = _capture_text(stdout_file)
        stderr = _capture_text(stderr_file)
        return (None if timed_out else process.returncode), stdout, stderr, timed_out, termination
