"""Decision-specific PEC retrieval orchestration."""
from __future__ import annotations

import time
from dataclasses import replace

from korpus.application.evidence_state import build_evidence_state
from korpus.application.predictive_evidence_control import RetrievalAction
from korpus.application.query_plan import QueryPlan, build_plan


def adaptive_retrieval_impl(
    *, identity, query_text, corpora, as_of, risk, admission_thresholds, retriever, planner,
    controller, answer_calibration_id, corpus_release_id, eligible_count, outcome_type,
    semantic_protocol, observed, search_one, search_plan, merge,
):
    started = time.monotonic()
    if controller is None:
        plan = build_plan(query_text, planner)
        return outcome_type(search_plan(retriever, identity, plan, corpora, as_of), plan, None)
    semantic_capable = isinstance(retriever, semantic_protocol)
    first = search_one(
        retriever, identity, query_text, corpora, as_of,
        semantic_enabled=False if semantic_capable else None,
    )
    state = build_evidence_state(
        query=query_text,
        risk=risk,
        evidence=first,
        eligible_evidence_count=eligible_count(first),
        admission_thresholds=admission_thresholds,
        semantic_available=semantic_capable and retriever.semantic_available(),
        budget_state={"cycles_used": 1, "evidence_items": len(first), "conflicts": 0},
    )
    trace = controller.decide(
        state,
        corpus_release_id=corpus_release_id,
        answer_calibration_id=answer_calibration_id,
    )
    action = trace.effective_action
    if action is RetrievalAction.BASELINE:
        plan = build_plan(query_text, planner)
        extra = search_plan(retriever, identity, plan, corpora, as_of, include_asked=False)
        return observed(outcome_type(
            merge(first, extra), plan, replace(trace, planner_executed=planner is not None)
        ), started)
    if action is RetrievalAction.STOP_USE_CURRENT_EVIDENCE:
        return observed(outcome_type(first, QueryPlan(asked=query_text), trace), started)
    if action is RetrievalAction.ABSTAIN:
        return observed(outcome_type(first, QueryPlan(asked=query_text), trace, early_abstain=True), started)
    if action is RetrievalAction.PLAN_QUERY_VARIANTS:
        plan = build_plan(query_text, planner)
        extra = search_plan(
            retriever, identity, plan, corpora, as_of,
            semantic_enabled=False if semantic_capable else None, include_asked=False,
        )
        return observed(outcome_type(
            merge(first, extra), plan, replace(trace, planner_executed=planner is not None)
        ), started)
    if action is RetrievalAction.ENABLE_SEMANTIC_RETRIEVAL:
        semantic = search_one(retriever, identity, query_text, corpora, as_of, semantic_enabled=True)
        return observed(outcome_type(
            merge(first, semantic), QueryPlan(asked=query_text), replace(trace, semantic_executed=True)
        ), started)
    if action is RetrievalAction.PLAN_AND_SEMANTIC:
        plan = build_plan(query_text, planner)
        semantic = search_plan(retriever, identity, plan, corpora, as_of, semantic_enabled=True)
        return observed(outcome_type(
            merge(first, semantic), plan,
            replace(trace, planner_executed=planner is not None, semantic_executed=True),
        ), started)
    return observed(outcome_type(first, QueryPlan(asked=query_text), trace), started)
