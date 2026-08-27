"""Ranking observations: aggregate metrics retain their worst-query evidence."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from korpus.application.adaptive_contracts import validate_judged_candidate
from korpus.application.retrieval import BM25Parameters, RetrievalWeights, score_candidates


@dataclass(frozen=True)
class JudgedCandidate:
    text: str
    relevance: int
    authority_score: float = 0.0
    semantic_score: float = 0.0
    temporal_score: float = 0.0

    def __post_init__(self) -> None:
        validate_judged_candidate(self)


@dataclass(frozen=True)
class JudgedQuery:
    query_id: str
    query: str
    candidates: tuple[JudgedCandidate, ...]

    def __post_init__(self) -> None:
        if not self.query_id or not self.query.strip() or not self.candidates:
            raise ValueError("judged query is incomplete")
        if not any(candidate.relevance > 0 for candidate in self.candidates):
            raise ValueError("judged query must contain relevant evidence")


@dataclass(frozen=True)
class RankingMetrics:
    evaluated_queries: int
    ndcg_at_10: float
    mrr_at_10: float
    recall_at_20: float
    worst_ndcg_at_10: float
    worst_reciprocal_rank_at_10: float
    worst_recall_at_20: float


def _dcg(grades: list[int]) -> float:
    gains: list[int] = [2**grade - 1 for grade in grades]
    return sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))


def _rank(query: JudgedQuery, weights: RetrievalWeights, bm25: BM25Parameters) -> list[int]:
    scored = score_candidates(
        query.query,
        [candidate.text for candidate in query.candidates],
        [candidate.authority_score >= 0.9 for candidate in query.candidates],
        bm25,
        authority_scores=[candidate.authority_score for candidate in query.candidates],
        semantic_scores=[candidate.semantic_score for candidate in query.candidates],
        temporal_scores=[candidate.temporal_score for candidate in query.candidates],
        weights=weights,
    )
    return [
        item.index for item in sorted(scored, key=lambda item: (-item.normalized_score, item.index))
    ]


def evaluate_ranking(
    dataset: Iterable[JudgedQuery], weights: RetrievalWeights, bm25: BM25Parameters
) -> RankingMetrics:
    queries = list(dataset)
    if not queries:
        raise ValueError("ranking dataset is empty")
    ndcg_values: list[float] = []
    reciprocal_ranks: list[float] = []
    recall_values: list[float] = []
    for query in queries:
        grades = [query.candidates[index].relevance for index in _rank(query, weights, bm25)]
        ideal_dcg = _dcg(sorted((item.relevance for item in query.candidates), reverse=True)[:10])
        ndcg_values.append(_dcg(grades[:10]) / ideal_dcg if ideal_dcg else 0.0)
        first = next((rank for rank, grade in enumerate(grades[:10], start=1) if grade > 0), None)
        reciprocal_ranks.append(0.0 if first is None else 1 / first)
        total = sum(item.relevance > 0 for item in query.candidates)
        recall_values.append(sum(grade > 0 for grade in grades[:20]) / total)
    count = len(queries)
    return RankingMetrics(
        count,
        sum(ndcg_values) / count,
        sum(reciprocal_ranks) / count,
        sum(recall_values) / count,
        min(ndcg_values),
        min(reciprocal_ranks),
        min(recall_values),
    )
