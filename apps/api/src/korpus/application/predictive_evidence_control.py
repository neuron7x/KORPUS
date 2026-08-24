"""Pure runtime evaluator for Predictive Evidence Control (PEC)."""
from __future__ import annotations

from dataclasses import dataclass
import math
from enum import StrEnum
from typing import Any

from korpus.application.controller_profile import ControllerProfile, RuleCondition
from korpus.application.evidence_state import EvidenceState
from korpus.application.pec_trace_projection import trace_audit_record


class RetrievalAction(StrEnum):
    STOP_USE_CURRENT_EVIDENCE = "STOP_USE_CURRENT_EVIDENCE"
    PLAN_QUERY_VARIANTS = "PLAN_QUERY_VARIANTS"
    ENABLE_SEMANTIC_RETRIEVAL = "ENABLE_SEMANTIC_RETRIEVAL"
    PLAN_AND_SEMANTIC = "PLAN_AND_SEMANTIC"
    ABSTAIN = "ABSTAIN"
    BASELINE = "BASELINE"


@dataclass(frozen=True, slots=True)
class ControllerTrace:
    profile_id: str
    profile_digest: str
    state_fingerprint: str
    predicted_action: RetrievalAction
    effective_action: RetrievalAction
    rule_id: str | None
    leaf_id: str | None
    admitted: bool
    fallback_reason: str | None
    shadow_mode: bool
    first_pass_sufficient: bool
    retrieval_gate_passed: bool = False
    minimum_admission_margin: float = -1.0
    decision_boundary_distance: float = 1.0
    planner_executed: bool = False
    semantic_executed: bool = False

    def as_audit_record(self) -> dict[str, object]:
        return trace_audit_record(self)



class PredictiveEvidenceController:
    """Evaluate an offline-promoted rule profile without network/model access."""

    def __init__(self, profile: ControllerProfile, *, shadow_mode: bool = True) -> None:
        self.profile = profile
        self.shadow_mode = shadow_mode

    def decide(
        self,
        state: EvidenceState,
        *,
        corpus_release_id: str,
        answer_calibration_id: str,
    ) -> ControllerTrace:
        binding_reason = self._binding_failure(corpus_release_id, answer_calibration_id)
        if binding_reason is not None:
            return self._fallback(state, binding_reason)
        for rule in self.profile.rules:
            if all(_condition_matches(state, condition) for condition in rule.conditions):
                leaf = rule.leaf
                support_reason = _support_failure(state, leaf.support)
                if support_reason is not None:
                    return self._fallback(state, support_reason, rule.rule_id, leaf.leaf_id)
                if not leaf.admitted:
                    return self._fallback(state, "leaf_not_admitted", rule.rule_id, leaf.leaf_id)
                predicted = RetrievalAction(leaf.action)
                if predicted in {
                    RetrievalAction.ENABLE_SEMANTIC_RETRIEVAL,
                    RetrievalAction.PLAN_AND_SEMANTIC,
                } and not state.semantic_available:
                    return self._fallback(
                        state, "semantic_retrieval_unavailable", rule.rule_id, leaf.leaf_id
                    )
                effective = RetrievalAction.BASELINE if self.shadow_mode else predicted
                return ControllerTrace(
                    profile_id=self.profile.profile_id,
                    profile_digest=self.profile.digest,
                    state_fingerprint=state.fingerprint,
                    predicted_action=predicted,
                    effective_action=effective,
                    rule_id=rule.rule_id,
                    leaf_id=leaf.leaf_id,
                    admitted=True,
                    fallback_reason="shadow_mode" if self.shadow_mode else None,
                    shadow_mode=self.shadow_mode,
                    first_pass_sufficient=state.original_query_has_eligible_evidence,
                    retrieval_gate_passed=state.retrieval_gate_passed,
                    minimum_admission_margin=state.minimum_admission_margin,
                    decision_boundary_distance=state.decision_boundary_distance,
                )
        return self._fallback(state, "state_out_of_support")

    def _binding_failure(self, corpus_release_id: str, answer_calibration_id: str) -> str | None:
        if self.profile.admission_status != "PASS":
            return "profile_not_admitted"
        if self.profile.corpus_release_id != corpus_release_id:
            return "corpus_release_mismatch"
        if self.profile.answer_calibration_id != answer_calibration_id:
            return "answer_calibration_mismatch"
        return None

    def _fallback(
        self,
        state: EvidenceState,
        reason: str,
        rule_id: str | None = None,
        leaf_id: str | None = None,
    ) -> ControllerTrace:
        return ControllerTrace(
            profile_id=self.profile.profile_id,
            profile_digest=self.profile.digest,
            state_fingerprint=state.fingerprint,
            predicted_action=RetrievalAction.BASELINE,
            effective_action=RetrievalAction.BASELINE,
            rule_id=rule_id,
            leaf_id=leaf_id,
            admitted=False,
            fallback_reason=reason,
            shadow_mode=self.shadow_mode,
            first_pass_sufficient=state.original_query_has_eligible_evidence,
            retrieval_gate_passed=state.retrieval_gate_passed,
            minimum_admission_margin=state.minimum_admission_margin,
            decision_boundary_distance=state.decision_boundary_distance,
        )


def _condition_matches(state: EvidenceState, condition: RuleCondition) -> bool:
    actual = state.feature_value(condition.feature)
    expected: Any = condition.value
    if condition.operator == "eq":
        return actual == expected
    if condition.operator == "ne":
        return actual != expected
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return False
    if not isinstance(expected, (int, float)) or isinstance(expected, bool):
        return False
    if not math.isfinite(float(actual)) or not math.isfinite(float(expected)):
        return False
    if condition.operator == "lt":
        return actual < expected
    if condition.operator == "le":
        return actual <= expected
    if condition.operator == "gt":
        return actual > expected
    if condition.operator == "ge":
        return actual >= expected
    return False


def _support_failure(state: EvidenceState, support: dict[str, Any]) -> str | None:
    for name, bounds in support.items():
        value = state.feature_value(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return f"unsupported_non_numeric_feature:{name}"
        if not math.isfinite(float(value)):
            return f"unsupported_non_finite_feature:{name}"
        if bounds.minimum is not None and value < bounds.minimum:
            return f"state_below_support:{name}"
        if bounds.maximum is not None and value > bounds.maximum:
            return f"state_above_support:{name}"
    return None
