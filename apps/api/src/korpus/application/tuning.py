from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Iterable

from korpus.application.retrieval import BM25Parameters, RetrievalWeights, score_candidates


@dataclass(frozen=True)
class JudgedCandidate:
    text: str
    relevance: int
    authority_score: float = 0.0
    temporal_score: float = 0.0

    def __post_init__(self) -> None:
        if self.relevance < 0 or self.relevance > 3:
            raise ValueError("relevance must be an integer in [0, 3]")
        if not 0 <= self.authority_score <= 1 or not 0 <= self.temporal_score <= 1:
            raise ValueError("component scores must be in [0, 1]")


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


@dataclass(frozen=True)
class TuningResult:
    weights: RetrievalWeights
    bm25: BM25Parameters
    metrics: RankingMetrics
    utility: float


def _dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades))


def _rank(query: JudgedQuery, weights: RetrievalWeights, bm25: BM25Parameters) -> list[int]:
    scored = score_candidates(
        query.query,
        [candidate.text for candidate in query.candidates],
        [candidate.authority_score >= 0.9 for candidate in query.candidates],
        bm25,
        authority_scores=[candidate.authority_score for candidate in query.candidates],
        temporal_scores=[candidate.temporal_score for candidate in query.candidates],
        weights=weights,
    )
    ordered = sorted(scored, key=lambda item: (-item.normalized_score, item.index))
    return [item.index for item in ordered]


def evaluate_ranking(
    dataset: Iterable[JudgedQuery],
    weights: RetrievalWeights,
    bm25: BM25Parameters,
) -> RankingMetrics:
    queries = list(dataset)
    if not queries:
        raise ValueError("ranking dataset is empty")
    ndcg_values: list[float] = []
    reciprocal_ranks: list[float] = []
    recall_values: list[float] = []
    for query in queries:
        order = _rank(query, weights, bm25)
        grades = [query.candidates[index].relevance for index in order]
        ideal = sorted((candidate.relevance for candidate in query.candidates), reverse=True)
        ideal_dcg = _dcg(ideal[:10])
        ndcg_values.append(_dcg(grades[:10]) / ideal_dcg if ideal_dcg else 0.0)
        first_relevant = next((rank for rank, grade in enumerate(grades[:10], start=1) if grade > 0), None)
        reciprocal_ranks.append(0.0 if first_relevant is None else 1 / first_relevant)
        total_relevant = sum(candidate.relevance > 0 for candidate in query.candidates)
        retrieved_relevant = sum(grade > 0 for grade in grades[:20])
        recall_values.append(retrieved_relevant / total_relevant)
    count = len(queries)
    return RankingMetrics(
        evaluated_queries=count,
        ndcg_at_10=sum(ndcg_values) / count,
        mrr_at_10=sum(reciprocal_ranks) / count,
        recall_at_20=sum(recall_values) / count,
    )


def _simplex_weight_candidates(step: float = 0.1) -> Iterable[RetrievalWeights]:
    if step <= 0 or step > 0.5 or not math.isclose(round(1 / step) * step, 1.0, abs_tol=1e-9):
        raise ValueError("step must evenly divide 1")
    units = round(1 / step)
    # Keep authority and temporal priors nonzero; otherwise trusted-current evidence
    # can be dominated by keyword stuffing.
    for lexical, coverage, character, authority, phrase in itertools.product(range(units + 1), repeat=5):
        temporal = units - lexical - coverage - character - authority - phrase
        if temporal < 0:
            continue
        if lexical < 2 or coverage < 1 or authority < 1:
            continue
        yield RetrievalWeights(
            lexical=lexical * step,
            query_coverage=coverage * step,
            character=character * step,
            authority=authority * step,
            phrase=phrase * step,
            temporal=temporal * step,
        )


def tune_ranking(
    dataset: Iterable[JudgedQuery],
    *,
    weight_step: float = 0.1,
    bm25_candidates: tuple[BM25Parameters, ...] = (
        BM25Parameters(0.9, 0.4),
        BM25Parameters(1.2, 0.6),
        BM25Parameters(1.5, 0.75),
        BM25Parameters(2.0, 0.85),
    ),
) -> TuningResult:
    queries = tuple(dataset)
    if len(queries) < 2:
        raise ValueError("at least two judged queries are required for tuning")
    best: TuningResult | None = None
    for bm25 in bm25_candidates:
        for weights in _simplex_weight_candidates(weight_step):
            metrics = evaluate_ranking(queries, weights, bm25)
            # Recall is a hard capability term; MRR and nDCG differentiate top ranks.
            utility = 0.50 * metrics.ndcg_at_10 + 0.30 * metrics.recall_at_20 + 0.20 * metrics.mrr_at_10
            candidate = TuningResult(weights=weights, bm25=bm25, metrics=metrics, utility=utility)
            if best is None or (candidate.utility, candidate.metrics.recall_at_20, candidate.weights.as_tuple()) > (
                best.utility,
                best.metrics.recall_at_20,
                best.weights.as_tuple(),
            ):
                best = candidate
    assert best is not None
    return best
