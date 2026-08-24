"""Finite-sample numerical contracts for TEVV."""
from __future__ import annotations

from korpus.application.numeric_contracts import finite_number, strict_int
from korpus.application.statistical_bounds import wilson_score_interval


def wilson_bounds(successes: object, total: object, z: object) -> tuple[float, float]:
    return wilson_score_interval(successes, total, z=z)


def validate_tevv_policy(max_width: object, minimum: object) -> tuple[float, int]:
    if not finite_number(max_width) or not 0 < float(max_width) <= 1:
        raise ValueError("maximum_interval_width must be finite and in (0, 1]")
    if not strict_int(minimum) or minimum < 1:
        raise ValueError("minimum_observations must be a positive integer")
    return float(max_width), minimum
