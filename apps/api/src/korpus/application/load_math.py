"""Fail-closed arithmetic for production load SLO evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from korpus.application.numeric_contracts import bounded_number, nonnegative_count


def _count_5xx(phase: Mapping[str, Any]) -> int:
    statuses = phase.get("statuses", {})
    if not isinstance(statuses, Mapping):
        return 0
    counts = [
        nonnegative_count(v, allow_digit_string=True)
        for k, v in statuses.items()
        if str(k).startswith("5")
    ]
    return -1 if any(v is None for v in counts) else sum(v for v in counts if v is not None)


def evaluate_load_numbers(
    report: Mapping[str, Any], steady_limit: float, cold_limit: float, throttle_reason: str
) -> dict[str, bool]:
    soak = report.get("soak", {})
    cold = report.get("cold_first_request", {})
    soak = soak if isinstance(soak, Mapping) else {}
    cold = cold if isinstance(cold, Mapping) else {}
    refusals = soak.get("refusal_reasons", {})
    decisions = soak.get("decisions", {})
    refusals = refusals if isinstance(refusals, Mapping) else {}
    decisions = decisions if isinstance(decisions, Mapping) else {}
    steady = bounded_number(soak.get("p95_seconds"), 0, steady_limit)
    start = bounded_number(cold.get("seconds"), 0, cold_limit)
    subject = nonnegative_count(refusals.get(throttle_reason, 0), allow_digit_string=True)
    deadlines = nonnegative_count(
        decisions.get("retrieval_deadline_exceeded", 0), allow_digit_string=True
    )
    return {
        "load_slo_steady_p95": steady is not None,
        "load_slo_cold_start": start is not None,
        "load_slo_no_5xx_rated": _count_5xx(soak) == 0,
        "load_slo_no_subject_throttle_rated": subject == 0,
        "load_slo_no_retrieval_deadline": deadlines == 0,
    }
