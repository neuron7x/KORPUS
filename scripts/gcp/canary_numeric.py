"""Strict numeric contracts for Cloud Run canary admission."""

from __future__ import annotations

import math


def _strict_int(value: object) -> bool:
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
    if not _strict_int(minimum_samples) or minimum_samples < 1:
        raise ValueError("minimum_samples must be a positive integer")
    _error_rate(maximum_error_rate)


def validate_timing(window_seconds: object, wait_seconds: object, poll_seconds: object) -> None:
    if not all(_strict_int(value) for value in (window_seconds, wait_seconds, poll_seconds)):
        raise ValueError("canary timing values must be integers")
    if window_seconds < 60 or wait_seconds < 0 or poll_seconds < 1:
        raise ValueError("invalid metric timing policy")
