from korpus.application.pec_contextual_benchmark import evaluate_contextual_benchmark


def row(query_id: str, baseline_rank: int | None, contextual_rank: int | None) -> dict[str, object]:
    return {
        "query_id": query_id,
        "baseline_hit": baseline_rank is not None,
        "baseline_rank": baseline_rank,
        "contextual_hit": contextual_rank is not None,
        "contextual_rank": contextual_rank,
        "evidence_unchanged": True,
        "citations_source_bound": True,
    }


def test_contextual_benchmark_requires_supported_paired_improvement() -> None:
    rows = [row(f"q{i}", 8, 1) for i in range(30)]
    report = evaluate_contextual_benchmark(rows, minimum_informative_pairs=20)
    assert report["status"] == "PASS"
    assert report["confidence_supported_improvement"] is True


def test_contextual_benchmark_fails_if_baseline_gold_is_lost() -> None:
    rows = [row("q1", 1, None), row("q2", 2, 1)]
    report = evaluate_contextual_benchmark(rows, minimum_informative_pairs=1)
    assert report["status"] == "FAIL"
    assert "baseline_gold_hit_lost:q1" in report["issues"]


def test_contextual_benchmark_refuses_evidence_mutation() -> None:
    item = row("q1", 2, 1)
    item["evidence_unchanged"] = False
    report = evaluate_contextual_benchmark([item], minimum_informative_pairs=1)
    assert report["status"] == "FAIL"
    assert "evidence_changed:q1" in report["issues"]


def test_contextual_benchmark_is_unknown_without_directional_evidence() -> None:
    rows = [row(f"q{i}", 1, 1) for i in range(50)]
    report = evaluate_contextual_benchmark(rows, minimum_informative_pairs=20)
    assert report["status"] == "UNKNOWN"
