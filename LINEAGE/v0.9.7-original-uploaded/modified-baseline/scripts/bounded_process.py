#!/usr/bin/env python3
"""Fail-closed primitive for bounded subprocess-tree execution."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from process_group_control import terminate_process_tree


def _fallback_output(process: subprocess.Popen[str], first: subprocess.TimeoutExpired) -> tuple[str, str]:
    for pipe in (process.stdout, process.stderr):
        if pipe is not None:
            pipe.close()
    return first.output or "", first.stderr or ""


def run_bounded(
    cmd: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout_seconds: float
) -> tuple[int | None, str, str, bool, str]:
    kwargs: dict[str, object] = {
        "cwd": cwd, "env": dict(env), "text": True,
        "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
    process = subprocess.Popen(list(cmd), **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return process.returncode, stdout, stderr, False, "not_required"
    except subprocess.TimeoutExpired as first:
        termination = terminate_process_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            stdout, stderr = _fallback_output(process, first)
        return None, stdout, stderr, True, termination
