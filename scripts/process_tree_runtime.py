#!/usr/bin/env python3
"""Bounded execution delegated to a private Linux child-subreaper supervisor."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path

from process_supervisor_client import supervise


def execute_bounded_process(
    cmd: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout_seconds: float
) -> tuple[int | None, str, str, bool, str]:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    return supervise(cmd, cwd=cwd, env=env, timeout_seconds=timeout_seconds)
