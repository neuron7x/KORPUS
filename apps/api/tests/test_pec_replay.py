from korpus.application.pec_replay import ReplayOutcome, dominates, solve_oracle
from korpus.application.predictive_evidence_control import RetrievalAction


def _row(action, *, latency=10, searches=1, planner=0, quality=True, error=False, auth=True):
    return ReplayOutcome(
        query_id="q1",
        group_id="g1",
        action=action,
        state_fingerprint="a" * 64,
        features={},
        authorization_ok=auth,
        answer_error=error,
        quality_ok=quality,
        answer_status="answered",
        gold_hit=True,
        latency_ms=latency,
        search_count=searches,
        planner_calls=planner,
        semantic_calls=0,
        candidate_count=8,
        external_tokens=0,
        provider_cost_microunits=0,
    )


def test_oracle_selects_unique_pareto_minimum_without_weighted_utility():
    stop = _row(RetrievalAction.STOP_USE_CURRENT_EVIDENCE, latency=5, searches=1)
    plan = _row(RetrievalAction.PLAN_QUERY_VARIANTS, latency=10, searches=2, planner=1)
    assert dominates(stop, plan)
    decision = solve_oracle([stop, plan])
    assert decision.action is RetrievalAction.STOP_USE_CURRENT_EVIDENCE
    assert decision.reason == "baseline_decision_already_admissible"


def test_oracle_refuses_to_invent_tradeoff_between_incomparable_resources():
    baseline = _row(RetrievalAction.STOP_USE_CURRENT_EVIDENCE, latency=1, searches=1, quality=False)
    fast_expensive = _row(RetrievalAction.PLAN_QUERY_VARIANTS, latency=5, searches=4)
    slow_cheap = _row(RetrievalAction.ENABLE_SEMANTIC_RETRIEVAL, latency=10, searches=1)
    decision = solve_oracle([baseline, fast_expensive, slow_cheap])
    assert decision.action is RetrievalAction.BASELINE
    assert decision.status == "UNKNOWN"


def test_unsafe_actions_are_removed_before_cost_optimization():
    unsafe = _row(RetrievalAction.STOP_USE_CURRENT_EVIDENCE, latency=1, auth=False)
    safe = _row(RetrievalAction.PLAN_QUERY_VARIANTS, latency=10, searches=2)
    assert solve_oracle([unsafe, safe]).action is RetrievalAction.PLAN_QUERY_VARIANTS


def test_oracle_requires_original_query_stop_baseline():
    plan = _row(RetrievalAction.PLAN_QUERY_VARIANTS, latency=5, searches=2)
    decision = solve_oracle([plan])
    assert decision.action is RetrievalAction.BASELINE
    assert decision.status == "UNKNOWN"
    assert decision.reason == "missing_original_query_stop_baseline"


def test_oracle_never_buys_compute_when_baseline_is_already_admissible_even_if_noisy_latency_is_lower():
    stop = _row(RetrievalAction.STOP_USE_CURRENT_EVIDENCE, latency=100, searches=1)
    plan = _row(RetrievalAction.PLAN_QUERY_VARIANTS, latency=1, searches=2, planner=1)
    decision = solve_oracle([stop, plan])
    assert decision.action is RetrievalAction.STOP_USE_CURRENT_EVIDENCE
    assert decision.reason == "baseline_decision_already_admissible"


def test_oracle_nonbaseline_compute_requires_baseline_failure_and_recovery():
    baseline = _row(
        RetrievalAction.STOP_USE_CURRENT_EVIDENCE,
        latency=1,
        quality=False,
    )
    plan = _row(RetrievalAction.PLAN_QUERY_VARIANTS, latency=10, searches=2, planner=1)
    decision = solve_oracle([baseline, plan])
    assert decision.action is RetrievalAction.PLAN_QUERY_VARIANTS
    assert decision.reason == "unique_pareto_minimum"
