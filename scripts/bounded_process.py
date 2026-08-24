#!/usr/bin/env python3
"""Fail-closed public primitive for bounded subprocess-tree execution."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from process_tree_runtime import execute_bounded_process


def run_bounded(
    cmd: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout_seconds: float
) -> tuple[int | None, str, str, bool, str]:
    return execute_bounded_process(
        cmd, cwd=cwd, env=env, timeout_seconds=timeout_seconds
    )
