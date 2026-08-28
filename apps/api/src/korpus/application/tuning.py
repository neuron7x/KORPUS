from __future__ import annotations

import itertools
from collections.abc import Iterable
from dataclasses import dataclass

from korpus.application.adaptive_contracts import validate_simplex_step
from korpus.application.ranking_evaluation import (
    JudgedCandidate,
    JudgedQuery,
    RankingMetrics,
    evaluate_ranking,
)
from korpus.application.retrieval import BM25Parameters, RetrievalWeights
from korpus.application.tuning_validation import (
    TuningValidationPolicy,
    validate_held_out,
    validate_partitions,
)

__all__ = [
    "JudgedCandidate",
    "JudgedQuery",
    "TuningValidationPolicy",
    "evaluate_ranking",
    "tune_ranking",
]


@dataclass(frozen=True)
class TuningResult:
    weights: RetrievalWeights
    bm25: BM25Parameters
    metrics: RankingMetrics
    utility: float
    validation_metrics: RankingMetrics
    validation_checks: tuple[tuple[str, bool], ...]


def _simplex_weight_candidates(step: float = 0.1) -> Iterable[RetrievalWeights]:
    step = validate_simplex_step(step)
    units = round(1 / step)
    # Authority remains nonzero to resist keyword stuffing. Semantic may be zero
    # when no independently validated embedding model exists.
    for lexical, semantic, coverage, character, authority, phrase in itertools.product(
        range(units + 1), repeat=6
    ):
        temporal = units - lexical - semantic - coverage - character - authority - phrase
        if temporal < 0:
            continue
        if lexical < 1 or coverage < 1 or authority < 1:
            continue
        yield RetrievalWeights(
            lexical=lexical * step,
            semantic=semantic * step,
            query_coverage=coverage * step,
            character=character * step,
            authority=authority * step,
            phrase=phrase * step,
            temporal=temporal * step,
        )


def tune_ranking(
    dataset: Iterable[JudgedQuery],
    validation_dataset: Iterable[JudgedQuery],
    *,
    weight_step: float = 0.1,
    bm25_candidates: tuple[BM25Parameters, ...] = (
        BM25Parameters(0.9, 0.4),
        BM25Parameters(1.2, 0.6),
        BM25Parameters(1.5, 0.75),
        BM25Parameters(2.0, 0.85),
    ),
    validation_policy: TuningValidationPolicy | None = None,
) -> TuningResult:
    validation_policy = validation_policy or TuningValidationPolicy()
    queries = tuple(dataset)
    validation_queries = tuple(validation_dataset)
    validate_partitions(queries, validation_queries)
    if not bm25_candidates:
        raise ValueError("at least one BM25 candidate is required")
    best: tuple[RetrievalWeights, BM25Parameters, RankingMetrics, float] | None = None
    for bm25 in bm25_candidates:
        for weights in _simplex_weight_candidates(weight_step):
            metrics = evaluate_ranking(queries, weights, bm25)
            # This scalar is diagnostic only. Selection is maximin first: a strong
            # average cannot compensate for abandoning the weakest query.
            utility = 0.50 * metrics.ndcg_at_10 + 0.30 * metrics.recall_at_20 + 0.20 * metrics.mrr_at_10
            candidate = (weights, bm25, metrics, utility)
            if best is None or (
                metrics.worst_recall_at_20,
                metrics.worst_reciprocal_rank_at_10,
                metrics.worst_ndcg_at_10,
                utility,
                weights.as_tuple(),
            ) > (
                best[2].worst_recall_at_20,
                best[2].worst_reciprocal_rank_at_10,
                best[2].worst_ndcg_at_10,
                best[3],
                best[0].as_tuple(),
            ):
                best = candidate
    if best is None:
        raise RuntimeError("ranking candidate search produced no result")
    weights, bm25, metrics, utility = best
    validation, checks = validate_held_out(validation_queries, weights, bm25, validation_policy)
    return TuningResult(weights, bm25, metrics, utility, validation, checks)
