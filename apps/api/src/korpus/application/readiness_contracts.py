"""Fail-closed criterion and target validation for readiness scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from korpus.application.numeric_contracts import bounded_number


def count_boolean_criteria(
    results: Mapping[str, Any], criterion_ids: Sequence[str], dimension_id: str
) -> int:
    invalid = sorted(key for key, value in results.items() if not isinstance(value, bool))
    if invalid:
        raise ValueError(f"dimension {dimension_id} criterion results must be booleans: {invalid}")
    return sum(results.get(criterion_id) is True for criterion_id in criterion_ids)


def readiness_target(value: object) -> float:
    target = bounded_number(value, 0.0, 100.0)
    if target is None:
        raise ValueError("target_percent must be finite and in [0, 100]")
    return target
