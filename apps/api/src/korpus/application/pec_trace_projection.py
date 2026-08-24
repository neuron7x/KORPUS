"""Stable audit projection for PEC controller traces."""

from __future__ import annotations

from typing import Protocol


class TraceLike(Protocol):
    """Read-only structural contract accepted by the stable audit projection."""

    @property
    def profile_id(self) -> str: ...

    @property
    def profile_digest(self) -> str: ...

    @property
    def state_fingerprint(self) -> str: ...

    @property
    def predicted_action(self) -> object: ...

    @property
    def effective_action(self) -> object: ...

    @property
    def rule_id(self) -> str | None: ...

    @property
    def leaf_id(self) -> str | None: ...

    @property
    def admitted(self) -> bool: ...

    @property
    def fallback_reason(self) -> str | None: ...

    @property
    def shadow_mode(self) -> bool: ...

    @property
    def first_pass_sufficient(self) -> bool: ...

    @property
    def retrieval_gate_passed(self) -> bool: ...

    @property
    def minimum_admission_margin(self) -> float: ...

    @property
    def decision_boundary_distance(self) -> float: ...

    @property
    def planner_executed(self) -> bool: ...

    @property
    def semantic_executed(self) -> bool: ...


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
