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
    order: list[str] = []
    searches = plan.searches if include_asked else plan.variants
    for text in searches:
        for item in _search_one(
            retriever, identity, text, corpora, as_of, semantic_enabled=semantic_enabled
        ):
            key = str(item.span.id)
            previous = best.get(key)
            if previous is None:
                order.append(key)
            if previous is None or item.score > previous.score:
                best[key] = item
    #: Порядок ЗБЕРІГАЄТЬСЯ, як і в `_merge`. Пересортування за сирою оцінкою тут
    #: скасовувало ранжування, яке щойно побудував `diversify_evidence` — лексикографічне,
    #: де схожість є лише тайбрейком усередині класу. Це та сама вада, що була в `_merge`,
    #: але саме ЦЯ функція стоїть на шляху, яким ходить розгортання: без каліброваного
    #: контролера `adaptive_retrieval_impl` повертає `search_plan(...)` першим же рядком.
    #:
    #: Ціна була виміряна: стаття «Обов'язки: Вивідний» приходить із пошуку ПЕРШОЮ і має
    #: найнижчу сиру оцінку (0.181), бо не повторює слів питання. Пересортування ставило
    #: її в кінець, а поріг допуску 0.25 добивав. На 92 оголошені предмети перша цитата
    #: жодного разу не була документом про предмет — нуль зі ста одного.
    return [best[key] for key in order]


def _merge(*groups: list[RetrievedEvidence]) -> list[RetrievedEvidence]:
    best: dict[str, RetrievedEvidence] = {}
    for group in groups:
        for item in group:
            key = str(item.span.id)
            previous = best.get(key)
            if previous is None or item.score > previous.score:
                best[key] = item
    #: Порядок груп ЗБЕРІГАЄТЬСЯ, а не перебудовується за оцінкою. Пересортування тут
    #: скасовувало ранжування, яке щойно побудував `diversify_evidence`: він упорядковує
    #: лексикографічно — клас авторитету спершу, схожість лише як тайбрейк, — саме щоб
    #: «no amount of lexical similarity promotes a weaker source above a stronger one».
    #: Рядок нижче за течією робив рівно те, що той коментар забороняє, і разом із
    #: авторитетом викидав будь-який інший клас рангу. Варіанти запиту дописуються в
    #: хвіст: вони доповнюють, а не переставляють те, що вже впорядковано.
    ordered: list[RetrievedEvidence] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            key = str(item.span.id)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(best[key])
    return ordered
