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


def _labels(profile: dict[str, Any], field: str) -> list[str]:
    value = profile.get(field)
    if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v for v in value):
        raise ValueError(f"{field} must be a non-empty string list")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} must contain unique values")
    return value


def validate_tevv_profile(profile: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "minimum_observations": _count(profile, "minimum_observations", positive=True),
        "minimum_observations_per_required_cohort": _count(
            profile, "minimum_observations_per_required_cohort", positive=True
        ),
        "minimum_null_controls": _count(profile, "minimum_null_controls", positive=True),
        "maximum_interval_width": _rate(profile, "maximum_interval_width", positive=True),
        "minimum_pass_rate": _rate(profile, "minimum_pass_rate"),
    }
    result.update({field: _count(profile, field, positive=False) for field in _MAX_COUNTS})
    result["required_cohorts"] = _labels(profile, "required_cohorts")
    for field in (
        "deployment_simulation_required",
        "evaluation_cue_blinding_required",
        "dependency_failure_simulation_required",
        "gold_annotation_receipt_required",
    ):
        result[field] = _flag(profile, field)
    return result
