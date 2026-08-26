from korpus.application.gold_annotation import (
    Adjudication,
    Annotation,
    DatasetSplit,
    GoldAdmissionPolicy,
    GoldBindings,
    GoldLabel,
    evaluate_gold_annotations,
)


def _row(query: str, annotator: str, label: GoldLabel, *, split=DatasetSplit.HOLDOUT):
    return Annotation(
        query_id=query,
        annotator_id=annotator,
        qualification_id=f"qualification-{annotator}",
        split=split,
        label=label,
        evidence_version_ids=frozenset({f"version-{query}"})
        if label is GoldLabel.ANSWERABLE
        else frozenset(),
    )


def _policy() -> GoldAdmissionPolicy:
    return GoldAdmissionPolicy(minimum_queries=2, minimum_holdout_queries=1, minimum_kappa=0)


def test_independent_agreeing_pairs_pass_without_adjudication() -> None:
    rows = [
        _row("q1", "a", GoldLabel.ANSWERABLE),
        _row("q1", "b", GoldLabel.ANSWERABLE),
        _row("q2", "a", GoldLabel.ABSTAIN),
        _row("q2", "b", GoldLabel.ABSTAIN),
    ]

    report = evaluate_gold_annotations(rows, [], tuning_query_ids=frozenset(), policy=_policy())

    assert report["status"] == "PASS"
    assert report["metrics"]["cohen_kappa"] == 1.0


def test_disagreement_requires_independent_adjudication() -> None:
    rows = [_row("q1", "a", GoldLabel.ANSWERABLE), _row("q1", "b", GoldLabel.ABSTAIN)]
    policy = GoldAdmissionPolicy(minimum_queries=1, minimum_holdout_queries=1, minimum_kappa=-1)

    missing = evaluate_gold_annotations(rows, [], tuning_query_ids=frozenset(), policy=policy)
    dependent = evaluate_gold_annotations(
        rows,
        [
            Adjudication(
                query_id="q1",
                adjudicator_id="a",
                label=GoldLabel.AMBIGUOUS,
                rationale="Evidence remains genuinely ambiguous.",
            )
        ],
        tuning_query_ids=frozenset(),
        policy=policy,
    )

    assert "missing_adjudication:q1" in missing["issues"]
    assert "adjudicator_not_independent:q1" in dependent["issues"]


def test_holdout_leakage_and_non_independent_annotation_are_blocking() -> None:
    rows = [_row("q1", "a", GoldLabel.ANSWERABLE), _row("q1", "a", GoldLabel.ANSWERABLE)]
    policy = GoldAdmissionPolicy(minimum_queries=1, minimum_holdout_queries=1, minimum_kappa=-1)

    report = evaluate_gold_annotations(rows, [], tuning_query_ids=frozenset({"q1"}), policy=policy)

    assert report["status"] == "FAIL"
    assert "requires_exactly_two_independent_annotations:q1" in report["issues"]


def test_gold_bindings_reject_placeholder_or_malformed_identity() -> None:
    fields = {
        "source_tree_sha256": "a" * 64,
        "release": "v1",
        "corpus_release_sha256": "b" * 64,
        "query_set_sha256": "c" * 64,
        "annotation_protocol_sha256": "d" * 64,
        "annotator_registry_sha256": "e" * 64,
        "model_id": "model-v1",
        "configuration_sha256": "f" * 64,
    }
    assert GoldBindings.model_validate(fields).model_id == "model-v1"

    fields["source_tree_sha256"] = "REPLACE_64_HEX"
    try:
        GoldBindings.model_validate(fields)
    except ValueError:
        pass
    else:
        raise AssertionError("placeholder source identity was accepted")
