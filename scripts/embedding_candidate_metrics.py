from __future__ import annotations

from typing import Any


def retrieval_metrics(
    queries: list[list[float]], candidates: list[list[float]], relevant: list[set[int]]
) -> dict[str, Any]:
    if not queries or len(queries) != len(relevant) or not candidates:
        raise ValueError("queries, candidates and relevance labels must be non-empty and aligned")
    ranks: list[int] = []
    for query, holders in zip(queries, relevant, strict=True):
        if not holders or max(holders) >= len(candidates):
            raise ValueError("every query must name an in-range relevant candidate")
        scored = sorted(
            ((sum(x * y for x, y in zip(query, candidate, strict=True)), index)
             for index, candidate in enumerate(candidates)),
            key=lambda item: (-item[0], item[1]),
        )
        ranks.append(min(rank for rank, (_, index) in enumerate(scored, 1) if index in holders))
    total = len(ranks)
    return {
        "queries": total,
        "recall_at_1": sum(rank <= 1 for rank in ranks) / total,
        "recall_at_5": sum(rank <= 5 for rank in ranks) / total,
        "recall_at_10": sum(rank <= 10 for rank in ranks) / total,
        "mrr": sum(1 / rank for rank in ranks) / total,
        "median_rank": sorted(ranks)[total // 2],
        "worst_rank": max(ranks),
    }
