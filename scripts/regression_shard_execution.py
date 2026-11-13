"""Regression receipt verdict; missing execution evidence cannot be PASS or FAIL."""

from __future__ import annotations

from collections.abc import Mapping


def execution_status(
    exit_code: int | None,
    timed_out: bool,
    counts: Mapping[str, int],
    selected_count: int,
) -> str:
    if timed_out or exit_code is None:
        return "UNKNOWN"
    if (
        exit_code == 0
        and counts["tests"] == selected_count
        and counts["failures"] == 0
        and counts["errors"] == 0
    ):
        return "PASS"
    return "FAIL"
