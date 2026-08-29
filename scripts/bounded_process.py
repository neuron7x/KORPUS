#!/usr/bin/env python3
"""Fail-closed public primitive for bounded subprocess-tree execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from process_tree_runtime import execute_bounded_process


def run_bounded(
    cmd: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout_seconds: float
) -> tuple[int | None, str, str, bool, str]:
    result: tuple[int | None, str, str, bool, str] = execute_bounded_process(
        cmd, cwd=cwd, env=env, timeout_seconds=timeout_seconds
    )
    return result
