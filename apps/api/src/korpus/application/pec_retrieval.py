"""Bounded retrieval orchestration for Predictive Evidence Control."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date

from korpus.application.pec_metrics_context import emit_pec_observation
from korpus.application.pec_retrieval_types import PECSearchOutcome, SemanticControllableRetriever
from korpus.application.ports import Retriever
from korpus.application.predictive_evidence_control import PredictiveEvidenceController
from korpus.application.query_plan import QueryPlan, QueryPlanner
from korpus.application.risk import QueryRisk, RiskThresholds
from korpus.domain.models import Identity, RetrievedEvidence


def _observed(outcome: PECSearchOutcome, started: float) -> PECSearchOutcome:
    emit_pec_observation(outcome.trace, time.monotonic() - started)
    return outcome


def adaptive_retrieval(
    *,
    identity: Identity,
    query_text: str,
    corpora: frozenset[str],
    as_of: date,
    risk: QueryRisk,
    admission_thresholds: RiskThresholds,
    retriever: Retriever,
    planner: QueryPlanner | None,
    controller: PredictiveEvidenceController | None,
    answer_calibration_id: str,
    corpus_release_id: str,
    eligible_count: Callable[[list[RetrievedEvidence]], int],
) -> PECSearchOutcome:
    from korpus.application.pec_adaptive_retrieval import adaptive_retrieval_impl

    return adaptive_retrieval_impl(
        identity=identity,
        query_text=query_text,
        corpora=corpora,
        as_of=as_of,
        risk=risk,
        admission_thresholds=admission_thresholds,
        retriever=retriever,
        planner=planner,
        controller=controller,
        answer_calibration_id=answer_calibration_id,
        corpus_release_id=corpus_release_id,
        eligible_count=eligible_count,
        outcome_type=PECSearchOutcome,
        observed=_observed,
        search_one=_search_one,
        search_plan=_search_plan,
        merge=_merge,
    )


def _search_one(
    retriever: Retriever,
    identity: Identity,
    text: str,
    corpora: frozenset[str],
    as_of: date,
    *,
    semantic_enabled: bool | None = None,
) -> list[RetrievedEvidence]:
    if semantic_enabled is not None and isinstance(retriever, SemanticControllableRetriever):
        return retriever.search_with_semantic(
            identity, text, corpora, as_of, semantic_enabled=semantic_enabled
        )
    return retriever.search(identity, text, corpora, as_of)


def _search_plan(
    retriever: Retriever,
    identity: Identity,
    plan: QueryPlan,
    corpora: frozenset[str],
    as_of: date,
    *,
    semantic_enabled: bool | None = None,
    include_asked: bool = True,
) -> list[RetrievedEvidence]:
    best: dict[str, RetrievedEvidence] = {}
    searches = plan.searches if include_asked else plan.variants
    for text in searches:
        for item in _search_one(
            retriever, identity, text, corpora, as_of, semantic_enabled=semantic_enabled
        ):
            key = str(item.span.id)
            previous = best.get(key)
            if previous is None or item.score > previous.score:
                best[key] = item
    return sorted(
        best.values(), key=lambda item: (-item.score, -item.query_coverage, item.span.ordinal)
    )


def _merge(*groups: list[RetrievedEvidence]) -> list[RetrievedEvidence]:
    best: dict[str, RetrievedEvidence] = {}
    for group in groups:
        for item in group:
            key = str(item.span.id)
            previous = best.get(key)
            if previous is None or item.score > previous.score:
                best[key] = item
    return sorted(
        best.values(), key=lambda item: (-item.score, -item.query_coverage, item.span.ordinal)
    )
