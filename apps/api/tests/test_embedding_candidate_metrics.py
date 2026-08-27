from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "embedding_candidate_metrics", ROOT / "scripts/embedding_candidate_metrics.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_metrics_use_best_relevant_rank_and_deterministic_ties() -> None:
    metrics = MODULE.retrieval_metrics(
        [[1.0, 0.0], [0.0, 1.0]],
        [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]],
        [{0, 2}, {1}],
    )

    assert metrics["recall_at_1"] == 1.0
    assert metrics["mrr"] == 1.0
    assert metrics["worst_rank"] == 1


@pytest.mark.parametrize(
    ("queries", "candidates", "relevant"),
    [([], [[1.0]], []), ([[1.0]], [], [{0}]), ([[1.0]], [[1.0]], [set()])],
)
def test_metrics_reject_broken_experimental_design(queries, candidates, relevant) -> None:
    with pytest.raises(ValueError):
        MODULE.retrieval_metrics(queries, candidates, relevant)
