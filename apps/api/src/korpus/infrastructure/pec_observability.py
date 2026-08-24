from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram

from korpus.application.predictive_evidence_control import ControllerTrace

_ACTIONS = frozenset({
    "STOP_USE_CURRENT_EVIDENCE", "PLAN_QUERY_VARIANTS", "ENABLE_SEMANTIC_RETRIEVAL",
    "PLAN_AND_SEMANTIC", "ABSTAIN", "BASELINE",
})
_FALLBACKS = frozenset({
    "none", "profile_not_admitted", "corpus_release_mismatch", "answer_calibration_mismatch",
    "leaf_not_admitted", "semantic_retrieval_unavailable", "state_out_of_support",
    "support_bound", "shadow_mode", "other",
})


def _fallback_label(reason: str | None) -> str:
    if reason is None:
        return "none"
    if reason.startswith(("state_below_support:", "state_above_support:", "unsupported_non_numeric_feature:")):
        return "support_bound"
    return reason if reason in _FALLBACKS else "other"


class PECMetrics:
    """Low-cardinality runtime metrics; judged error metrics remain offline-only."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.actions = Counter("korpus_pec_actions_total", "PEC effective actions.", ["action"], registry=registry)
        self.fallbacks = Counter("korpus_pec_fallbacks_total", "PEC bounded fallback reasons.", ["reason"], registry=registry)
        self.planner = Counter("korpus_pec_planner_total", "Planner execution under PEC.", ["executed"], registry=registry)
        self.semantic = Counter("korpus_pec_semantic_total", "Semantic retrieval execution under PEC.", ["executed"], registry=registry)
        self.first_pass = Counter("korpus_pec_first_pass_total", "First-pass evidence sufficiency.", ["sufficient"], registry=registry)
        self.out_of_support = Counter("korpus_pec_out_of_support_total", "PEC states outside admitted support.", registry=registry)
        self.latency = Histogram(
            "korpus_pec_retrieval_duration_seconds", "PEC retrieval orchestration latency.", ["action"],
            buckets=(0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1, 3), registry=registry,
        )

    def observe(self, trace: ControllerTrace, elapsed_seconds: float) -> None:
        action = trace.effective_action.value
        action = action if action in _ACTIONS else "BASELINE"
        fallback = _fallback_label(trace.fallback_reason)
        self.actions.labels(action=action).inc()
        self.fallbacks.labels(reason=fallback).inc()
        self.planner.labels(executed=str(trace.planner_executed).lower()).inc()
        self.semantic.labels(executed=str(trace.semantic_executed).lower()).inc()
        self.first_pass.labels(sufficient=str(trace.first_pass_sufficient).lower()).inc()
        if fallback in {"state_out_of_support", "support_bound"}:
            self.out_of_support.inc()
        self.latency.labels(action=action).observe(elapsed_seconds)
