import pytest
from korpus.application.retrieval import BM25Parameters, RetrievalWeights
from korpus.application.tuning import (
    JudgedCandidate,
    JudgedQuery,
    TuningValidationPolicy,
    evaluate_ranking,
    tune_ranking,
)


def dataset(prefix: str = "train"):
    return (
        JudgedQuery(
            query_id=f"{prefix}-q1",
            query="журнал перевірок дата відповідальна особа",
            candidates=(
                JudgedCandidate(
                    "Кожен запис журналу містить дату і відповідальну особу.", 3, 1.0, 1.0
                ),
                JudgedCandidate("Журнал може мати назву.", 1, 0.4, 0.0),
                JudgedCandidate("Погода мінлива.", 0, 1.0, 1.0),
            ),
        ),
        JudgedQuery(
            query_id=f"{prefix}-q2",
            query="строк чинності наказу",
            candidates=(
                JudgedCandidate("Наказ чинний до 31 грудня 2026 року.", 3, 1.0, 1.0),
                JudgedCandidate("Історичний наказ не містить строку.", 1, 0.3, 0.0),
                JudgedCandidate("Сторонній матеріал.", 0, 0.0, 0.0),
            ),
        ),
    )


def test_ranking_metrics_are_bounded_and_exact_target_is_first():
    metrics = evaluate_ranking(dataset(), RetrievalWeights(), BM25Parameters())
    assert metrics.evaluated_queries == 2
    assert 0 <= metrics.ndcg_at_10 <= 1
    assert metrics.mrr_at_10 == 1
    assert metrics.recall_at_20 == 1
    assert metrics.worst_recall_at_20 == 1


def test_tuner_is_deterministic_and_returns_convex_weights():
    first = tune_ranking(dataset(), dataset("validation"), weight_step=0.2)
    second = tune_ranking(dataset(), dataset("validation"), weight_step=0.2)
    assert first == second
    assert abs(sum(first.weights.as_tuple()) - 1.0) < 1e-9
    assert first.metrics.mrr_at_10 == 1
    assert all(passed for _, passed in first.validation_checks)


def test_tuner_rejects_reused_validation_queries_and_invalid_limits():
    with pytest.raises(ValueError, match="disjoint"):
        tune_ranking(dataset(), dataset(), weight_step=0.2)
    with pytest.raises(ValueError, match="finite"):
        TuningValidationPolicy(minimum_worst_recall_at_20=float("nan"))


def test_held_out_worst_query_failure_cannot_be_compensated_by_average():
    buried = tuple(
        [JudgedCandidate("строк чинності наказу", 0) for _ in range(10)]
        + [JudgedCandidate("нерелевантний до запиту текст", 3)]
    )
    held_out = (
        JudgedQuery("held-out-1", "строк чинності наказу", buried),
        JudgedQuery("held-out-2", "строк чинності наказу", buried),
    )
    with pytest.raises(ValueError, match="worst_reciprocal_rank_at_10"):
        tune_ranking(dataset(), held_out, weight_step=0.2)
