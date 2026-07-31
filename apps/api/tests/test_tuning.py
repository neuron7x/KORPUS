from korpus.application.retrieval import BM25Parameters, RetrievalWeights
from korpus.application.tuning import JudgedCandidate, JudgedQuery, evaluate_ranking, tune_ranking


def dataset():
    return (
        JudgedQuery(
            query_id="q1",
            query="журнал перевірок дата відповідальна особа",
            candidates=(
                JudgedCandidate("Кожен запис журналу містить дату і відповідальну особу.", 3, 1.0, 1.0),
                JudgedCandidate("Журнал може мати назву.", 1, 0.4, 0.0),
                JudgedCandidate("Погода мінлива.", 0, 1.0, 1.0),
            ),
        ),
        JudgedQuery(
            query_id="q2",
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


def test_tuner_is_deterministic_and_returns_convex_weights():
    first = tune_ranking(dataset(), weight_step=0.2)
    second = tune_ranking(dataset(), weight_step=0.2)
    assert first == second
    assert abs(sum(first.weights.as_tuple()) - 1.0) < 1e-9
    assert first.metrics.mrr_at_10 == 1
