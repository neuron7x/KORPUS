"""Held-out, conjunctive admission for learned retrieval parameters."""

from __future__ import annotations

import math
from dataclasses import dataclass

from korpus.application.ranking_evaluation import JudgedQuery, RankingMetrics, evaluate_ranking
from korpus.application.retrieval import BM25Parameters, RetrievalWeights


@dataclass(frozen=True)
class TuningValidationPolicy:
    minimum_worst_ndcg_at_10: float = 0.1
    minimum_worst_reciprocal_rank_at_10: float = 0.1
    minimum_worst_recall_at_20: float = 1.0
    require_baseline_non_regression: bool = True

    def __post_init__(self) -> None:
        values = (
            self.minimum_worst_ndcg_at_10,
            self.minimum_worst_reciprocal_rank_at_10,
            self.minimum_worst_recall_at_20,
        )
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
            raise ValueError("validation limits must be finite values in [0, 1]")


def validate_partitions(
    training: tuple[JudgedQuery, ...], validation: tuple[JudgedQuery, ...]
) -> None:
    if len(training) < 2:
        raise ValueError("at least two judged queries are required for tuning")
    if len(validation) < 2:
        raise ValueError("at least two held-out queries are required for validation")
    training_ids = [query.query_id for query in training]
    validation_ids = [query.query_id for query in validation]
    if len(set(training_ids)) != len(training_ids) or len(set(validation_ids)) != len(
        validation_ids
    ):
        raise ValueError("query ids must be unique inside each dataset")
    if set(training_ids) & set(validation_ids):
        raise ValueError("training and validation query ids must be disjoint")


def held_out_checks(
    validation: RankingMetrics, baseline: RankingMetrics, policy: TuningValidationPolicy
) -> tuple[tuple[str, bool], ...]:
    non_regression = (
        validation.worst_ndcg_at_10 >= baseline.worst_ndcg_at_10
        and validation.worst_reciprocal_rank_at_10 >= baseline.worst_reciprocal_rank_at_10
        and validation.worst_recall_at_20 >= baseline.worst_recall_at_20
    )
    return (
        ("worst_ndcg_at_10", validation.worst_ndcg_at_10 >= policy.minimum_worst_ndcg_at_10),
        (
            "worst_reciprocal_rank_at_10",
            validation.worst_reciprocal_rank_at_10 >= policy.minimum_worst_reciprocal_rank_at_10,
        ),
        ("worst_recall_at_20", validation.worst_recall_at_20 >= policy.minimum_worst_recall_at_20),
        ("baseline_non_regression", not policy.require_baseline_non_regression or non_regression),
    )


def validate_held_out(
    queries: tuple[JudgedQuery, ...],
    weights: RetrievalWeights,
    bm25: BM25Parameters,
    policy: TuningValidationPolicy,
) -> tuple[RankingMetrics, tuple[tuple[str, bool], ...]]:
    metrics = evaluate_ranking(queries, weights, bm25)
    baseline = evaluate_ranking(queries, RetrievalWeights(), BM25Parameters())
    checks = held_out_checks(metrics, baseline, policy)
    failed = [name for name, passed in checks if not passed]
    if failed:
        raise ValueError("held-out ranking validation failed: " + ", ".join(failed))
    return metrics, checks
