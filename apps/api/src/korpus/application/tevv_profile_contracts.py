"""Strict production-TEVV policy contracts; no numeric coercion."""

from __future__ import annotations

from typing import Any

from korpus.application.numeric_contracts import finite_number, strict_int

_MAX_COUNTS = (
    "maximum_citation_failures",
    "maximum_leakage_failures",
    "maximum_determinism_failures",
    "maximum_null_control_false_accepts",
)


def _count(profile: dict[str, Any], field: str, *, positive: bool) -> int:
    value = profile.get(field)
    if not strict_int(value) or value < (1 if positive else 0):
        raise ValueError(f"{field} must be a {'positive' if positive else 'non-negative'} integer")
    return value


def _rate(profile: dict[str, Any], field: str, *, positive: bool = False) -> float:
    value = profile.get(field)
    if not finite_number(value) or not (
        0 < float(value) <= 1 if positive else 0 <= float(value) <= 1
    ):
        raise ValueError(f"{field} must be a numeric rate in {'(0, 1]' if positive else '[0, 1]'}")
    return float(value)


def _flag(profile: dict[str, Any], field: str) -> bool:
    value = profile.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be boolean")
    return value


def validate_tevv_profile(profile: dict[str, Any]) -> dict[str, int | float | bool]:
    result: dict[str, int | float | bool] = {
        "minimum_observations": _count(profile, "minimum_observations", positive=True),
        "minimum_null_controls": _count(profile, "minimum_null_controls", positive=True),
        "maximum_interval_width": _rate(profile, "maximum_interval_width", positive=True),
        "minimum_pass_rate": _rate(profile, "minimum_pass_rate"),
    }
    result.update({field: _count(profile, field, positive=False) for field in _MAX_COUNTS})
    for field in (
        "deployment_simulation_required",
        "evaluation_cue_blinding_required",
        "dependency_failure_simulation_required",
        "gold_annotation_receipt_required",
    ):
        result[field] = _flag(profile, field)
    return result
