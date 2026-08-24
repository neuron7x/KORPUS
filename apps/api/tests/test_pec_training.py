from korpus.application.pec_training import TrainingRow, hoeffding_upper, train_tree


def test_tree_learns_observable_sufficiency_boundary_deterministically():
    rows = []
    for i in range(60):
        score = i / 59
        rows.append(
            TrainingRow(
                str(i),
                f"g{i // 2}",
                {"top1_score": score, "original_query_has_eligible_evidence": score >= 0.5},
                "STOP_USE_CURRENT_EVIDENCE" if score >= 0.5 else "PLAN_QUERY_VARIANTS",
            )
        )
    a = train_tree(rows, max_depth=2, min_leaf=5)
    b = train_tree(rows, max_depth=2, min_leaf=5)
    assert a == b
    assert (
        a.predict({"top1_score": 0.9, "original_query_has_eligible_evidence": True})
        == "STOP_USE_CURRENT_EVIDENCE"
    )
    assert (
        a.predict({"top1_score": 0.1, "original_query_has_eligible_evidence": False})
        == "PLAN_QUERY_VARIANTS"
    )


def test_hoeffding_bound_fails_closed_at_zero_samples():
    assert hoeffding_upper(0, 0, 0.05) == 1.0
    assert 0 < hoeffding_upper(0, 1000, 0.05) < 0.1
