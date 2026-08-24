from korpus.application.pec_metrics_context import (
    emit_pec_observation,
    reset_pec_observer,
    set_pec_observer,
)
from korpus.application.predictive_evidence_control import ControllerTrace, RetrievalAction
from korpus.infrastructure.pec_observability import PECMetrics
from prometheus_client import CollectorRegistry, generate_latest


def _trace(reason: str | None = None) -> ControllerTrace:
    return ControllerTrace(
        profile_id="p",
        profile_digest="a" * 64,
        state_fingerprint="b" * 64,
        predicted_action=RetrievalAction.PLAN_QUERY_VARIANTS,
        effective_action=RetrievalAction.PLAN_QUERY_VARIANTS,
        rule_id="r",
        leaf_id="l",
        admitted=True,
        fallback_reason=reason,
        shadow_mode=False,
        first_pass_sufficient=False,
        planner_executed=True,
    )


def test_pec_metrics_are_low_cardinality_and_context_local() -> None:
    registry = CollectorRegistry()
    metrics = PECMetrics(registry)
    token = set_pec_observer(metrics.observe)
    try:
        emit_pec_observation(_trace("state_below_support:top1_score"), 0.02)
    finally:
        reset_pec_observer(token)
    emit_pec_observation(_trace(), 0.02)
    text = generate_latest(registry).decode()
    assert 'korpus_pec_actions_total{action="PLAN_QUERY_VARIANTS"} 1.0' in text
    assert 'korpus_pec_fallbacks_total{reason="support_bound"} 1.0' in text
    assert 'korpus_pec_planner_total{executed="true"} 1.0' in text
    assert "korpus_pec_out_of_support_total 1.0" in text
    assert "top1_score" not in text
