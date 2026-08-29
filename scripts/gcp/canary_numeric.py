"""Strict numeric contracts for Cloud Run canary admission."""

from __future__ import annotations

import math

from typing_extensions import TypeIs


def _strict_int(value: object) -> TypeIs[int]:
    """TypeIs, not bool: the callers compare the value straight after asking."""
    return isinstance(value, int) and not isinstance(value, bool)


def request_count(value: object) -> int:
    if _strict_int(value):
        if value < 0:
            raise ValueError("request_count cannot be negative")
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    raise ValueError(f"invalid request_count value: {value!r}")


def _error_rate(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("maximum_error_rate must be numeric")
    rate = float(value)
    if not math.isfinite(rate) or rate < 0.0 or rate >= 1.0:
        raise ValueError("maximum_error_rate must be finite and in [0, 1)")
    return rate


def validate_summary_policy(minimum_samples: object, maximum_error_rate: object) -> None:
    if not _strict_int(minimum_samples):
        raise ValueError("minimum_samples must be a positive integer")
    if minimum_samples < 1:
        raise ValueError("minimum_samples must be a positive integer")
    _error_rate(maximum_error_rate)


def validate_timing(window_seconds: object, wait_seconds: object, poll_seconds: object) -> None:
    # Checked one at a time: `all(...)` over a generator narrows nothing, so the three
    # comparisons below would still be against `object`.
    if not _strict_int(window_seconds) or not _strict_int(wait_seconds):
        raise ValueError("canary timing values must be integers")
    if not _strict_int(poll_seconds):
        raise ValueError("canary timing values must be integers")
    if window_seconds < 60 or wait_seconds < 0 or poll_seconds < 1:
        raise ValueError("invalid metric timing policy")
