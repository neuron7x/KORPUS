from korpus.application.pec_research import (
    conditional_risk_report,
    observed_information_gain,
    production_judgment_validity,
    replay_priority_enrichment,
    simultaneous_hoeffding_upper,
)


def test_simultaneous_bound_is_more_conservative_with_more_strata() -> None:
    assert simultaneous_hoeffding_upper(0, 100, 0.05, 4) > simultaneous_hoeffding_upper(
        0, 100, 0.05, 1
    )


def test_conditional_risk_underpowered_stratum_falls_back() -> None:
    rows = [{"risk": "underpowered", "error": False} for _ in range(3)] + [
        {"risk": "sufficient_but_unsafe", "error": True} for _ in range(30)
    ]
    report = conditional_risk_report(
        rows, stratum_key="risk", error_key="error", risk_limit=0.2, delta=0.05, minimum_samples=30
    )
    assert report["status"] == "PASS"
    assert report["strata"]["underpowered"]["admitted"] is False
    assert report["strata"]["underpowered"]["fallback_required"] is True
    assert report["strata"]["sufficient_but_unsafe"]["admitted"] is False
    assert report["strata"]["sufficient_but_unsafe"]["fallback_required"] is True


def test_replay_priority_enriches_explicit_failures() -> None:
    rows = [{"query_id": f"q{i}"} for i in range(40)]
    for i in range(8):
        rows[i]["accepted_answer_error"] = True
    report = replay_priority_enrichment(rows, top_fraction=0.2, alpha=0.05)
    assert report["failures_captured"] == 8
    assert report["status"] == "PASS"


def test_information_gain_is_vector_not_weighted_scalar() -> None:
    rows = [
        {
            "query_id": "q",
            "action": "STOP_USE_CURRENT_EVIDENCE",
            "gold_hit": False,
            "quality_ok": False,
            "retrieval_quality": {"ndcg": 0.1},
            "search_count": 1,
            "planner_calls": 0,
            "semantic_calls": 0,
        },
        {
            "query_id": "q",
            "action": "PLAN_QUERY_VARIANTS",
            "gold_hit": True,
            "quality_ok": True,
            "retrieval_quality": {"ndcg": 0.7},
            "search_count": 3,
            "planner_calls": 1,
            "semantic_calls": 0,
        },
    ]
    report = observed_information_gain(rows)
    item = report["comparisons"][0]
    assert item["gold_hit_delta"] == 1
    assert item["retrieval_quality_deltas"]["ndcg"] == 0.6
    assert "utility" not in item


def test_production_judgment_requires_bound_provenance() -> None:
    report = production_judgment_validity(
        [
            {
                "id": "q",
                "production_judged": True,
                "judgment_provenance_sha256": "x" * 64,
                "adjudication_protocol": "v1",
            }
        ]
    )
    assert report["status"] == "FAIL"


def _training_fixture():
    from korpus.application.pec_training import TrainingRow

    return [
        TrainingRow(
            query_id=f"q{index}",
            group_id=f"g{index // 10}",
            features={"top1_score": float(index % 10) / 10.0, "query_token_count": index % 7 + 1},
            label="STOP_USE_CURRENT_EVIDENCE" if index % 10 >= 5 else "PLAN_QUERY_VARIANTS",
        )
        for index in range(120)
    ]


def test_nested_group_validation_is_outer_group_disjoint() -> None:
    from korpus.application.pec_training import nested_group_validation

    report = nested_group_validation(_training_fixture(), outer_folds=4)
    assert report["status"] == "PASS"
    assert report["evaluated_rows"] == 120
    assert all(fold["group_disjoint"] for fold in report["folds"])


def test_nested_selection_never_sees_outer_validation(monkeypatch) -> None:
    import korpus.application.pec_training_validation as validation

    data = _training_fixture()
    original = validation.select_hyperparameters
    seen: list[int] = []

    def guarded(rows):
        material = list(rows)
        seen.append(len(material))
        assert len(material) < len(data)
        return original(material)

    monkeypatch.setattr(validation, "select_hyperparameters", guarded)
    report = validation.nested_group_validation(data, outer_folds=4)
    assert report["status"] == "PASS"
    assert seen


def test_research_status_refuses_non_production_authority() -> None:
    from korpus.application.pec_research import research_status

    status, authority = research_status({"status": "UNKNOWN"}, [{"status": "PASS"}])
    assert status == "UNKNOWN"
    assert authority is False
