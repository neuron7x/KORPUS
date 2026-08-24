"""Stable audit projection for PEC controller traces."""
from __future__ import annotations

from typing import Protocol


class TraceLike(Protocol):
    profile_id: str
    profile_digest: str
    state_fingerprint: str
    predicted_action: object
    effective_action: object
    rule_id: str | None
    leaf_id: str | None
    admitted: bool
    fallback_reason: str | None
    shadow_mode: bool
    first_pass_sufficient: bool
    retrieval_gate_passed: bool
    minimum_admission_margin: float
    decision_boundary_distance: float
    planner_executed: bool
    semantic_executed: bool


def trace_audit_record(trace: TraceLike) -> dict[str, object]:
    return {
        "profile_id": trace.profile_id,
        "profile_digest": trace.profile_digest,
        "state_fingerprint": trace.state_fingerprint,
        "predicted_action": str(getattr(trace.predicted_action, "value", trace.predicted_action)),
        "effective_action": str(getattr(trace.effective_action, "value", trace.effective_action)),
        "rule_id": trace.rule_id,
        "leaf_id": trace.leaf_id,
        "admitted": trace.admitted,
        "fallback_reason": trace.fallback_reason,
        "shadow_mode": trace.shadow_mode,
        "first_pass_sufficient": trace.first_pass_sufficient,
        "retrieval_gate_passed": trace.retrieval_gate_passed,
        "minimum_admission_margin": trace.minimum_admission_margin,
        "decision_boundary_distance": trace.decision_boundary_distance,
        "planner_executed": trace.planner_executed,
        "semantic_executed": trace.semantic_executed,
    }
