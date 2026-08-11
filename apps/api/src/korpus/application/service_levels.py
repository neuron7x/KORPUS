from __future__ import annotations

from collections.abc import Mapping
from typing import Any

STEADY_P95_LIMIT_SECONDS = 5.0
COLD_START_LIMIT_SECONDS = 5.0
SUBJECT_THROTTLE_REASON = "subject_share_exhausted"


def _count_5xx(phase: Mapping[str, Any]) -> int:
    statuses = phase.get("statuses", {})
    if not isinstance(statuses, Mapping):
        return 0
    return sum(int(count) for code, count in statuses.items() if str(code).startswith("5"))


def evaluate_load_slos(report: Mapping[str, Any]) -> dict[str, bool]:
    """Evaluate production-relevant load quality independently of provenance.

    A trusted signature proves who produced evidence, not that the measured system met
    its objective. These predicates therefore remain separate from environment and
    attestation checks.
    """
    soak = report.get("soak", {})
    cold = report.get("cold_first_request", {})
    if not isinstance(soak, Mapping):
        soak = {}
    if not isinstance(cold, Mapping):
        cold = {}
    refusals = soak.get("refusal_reasons", {})
    decisions = soak.get("decisions", {})
    if not isinstance(refusals, Mapping):
        refusals = {}
    if not isinstance(decisions, Mapping):
        decisions = {}
    return {
        "load_slo_steady_p95": float(soak.get("p95_seconds", float("inf"))) <= STEADY_P95_LIMIT_SECONDS,
        "load_slo_cold_start": float(cold.get("seconds", float("inf"))) <= COLD_START_LIMIT_SECONDS,
        "load_slo_no_5xx_rated": _count_5xx(soak) == 0,
        "load_slo_no_subject_throttle_rated": int(refusals.get(SUBJECT_THROTTLE_REASON, 0)) == 0,
        "load_slo_no_retrieval_deadline": int(decisions.get("retrieval_deadline_exceeded", 0)) == 0,
    }
