from __future__ import annotations

import math

import pytest

from korpus.application.evidence_state import _round
from korpus.application.numeric_contracts import finite_number
from korpus.application.pec_replay import ReplayOutcome
from korpus.application.predictive_evidence_control import RetrievalAction
from korpus.application.risk import RiskThresholds, risk_adjusted_thresholds
from korpus.application.risk_rules import QueryRisk
from korpus.application.statistical_bounds import (
    hoeffding_two_sided_interval,
    hoeffding_upper_bound,
    wilson_score_interval,
)
from scripts.pec_replay_validation import record_issues


def _outcome(**overrides: object) -> ReplayOutcome:
    values: dict[str, object] = {
        "query_id": "q1",
        "group_id": "g1",
        "action": RetrievalAction.STOP_USE_CURRENT_EVIDENCE,
        "state_fingerprint": "a" * 64,
        "features": {},
        "authorization_ok": True,
        "answer_error": False,
        "quality_ok": True,
        "answer_status": "answered",
        "gold_hit": True,
        "latency_ms": 1.0,
        "search_count": 1,
        "planner_calls": 0,
        "semantic_calls": 0,
        "candidate_count": 1,
        "external_tokens": 0,
        "provider_cost_microunits": 0,
    }
    values.update(overrides)
    return ReplayOutcome(**values)  # type: ignore[arg-type]


def test_finite_number_is_total_for_unrepresentable_integer() -> None:
    assert finite_number(10**10000) is False


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, -0.01])
def test_replay_outcome_rejects_invalid_latency(bad: float) -> None:
    with pytest.raises(ValueError, match="latency_ms"):
        _outcome(latency_ms=bad)


@pytest.mark.parametrize("field", ["search_count", "planner_calls", "semantic_calls", "candidate_count", "external_tokens", "provider_cost_microunits"])
def test_replay_outcome_rejects_negative_resource_counts(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        _outcome(**{field: -1})


def test_replay_validator_rejects_nan_measurement_and_fractional_rank() -> None:
    row = {
        "query_id": "q1", "group_id": "g1", "action": "STOP_USE_CURRENT_EVIDENCE",
        "state_fingerprint": "a" * 64, "features": {},
        "authorization_ok": True, "answer_error": False, "quality_ok": True,
        "answer_status": "answered", "gold_hit": True,
        "latency_ms": math.nan, "search_count": 1, "planner_calls": 0,
        "semantic_calls": 0, "candidate_count": 1,
        "corpus_release_id": "r", "evaluation_protocol_sha256": "b" * 64,
        "answer_calibration_id": "c", "risk_class": "standard", "judgment": "ok",
        "retrieved_spans": [{"span_id": "s", "rank": 1.5}],
        "retrieval_quality": {}, "evidence_fingerprints": [],
    }
    issues = record_issues(
        row, dataset_by_id={"q1": {"group_id": "g1"}},
        actions=("STOP_USE_CURRENT_EVIDENCE",), expected_corpus_release_id="r",
        expected_protocol_sha256="b" * 64, expected_answer_calibration_id="c",
        require_bindings=True,
    )
    assert any("invalid_measurement:q1:STOP_USE_CURRENT_EVIDENCE:latency_ms" == issue for issue in issues)
    assert any("invalid_retrieved_rank:q1:STOP_USE_CURRENT_EVIDENCE:0" == issue for issue in issues)


def test_nan_cannot_be_canonicalized_to_maximum_probability() -> None:
    with pytest.raises(ValueError, match="finite"):
        _round(math.nan)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -0.1, 1.1, True])
def test_risk_thresholds_reject_non_probability_domain(bad: object) -> None:
    with pytest.raises(ValueError):
        RiskThresholds(bad, 0.5, 0.5, 0.5)  # type: ignore[arg-type]


def test_risk_adjustment_rejects_nan_before_min_clamping() -> None:
    with pytest.raises(ValueError):
        risk_adjusted_thresholds(
            QueryRisk.OPERATIONAL,
            minimum_score=math.nan,
            minimum_query_coverage=0.5,
            minimum_support_score=0.5,
        )


@pytest.mark.parametrize("fn", [wilson_score_interval, hoeffding_upper_bound])
def test_statistical_bounds_reject_boolean_counts(fn: object) -> None:
    with pytest.raises(ValueError):
        if fn is wilson_score_interval:
            wilson_score_interval(True, 10)
        else:
            hoeffding_upper_bound(True, 10, 0.05)


def test_two_sided_hoeffding_is_fail_closed_at_zero_samples() -> None:
    assert hoeffding_two_sided_interval(0, 0, 0.05) == (0.0, 1.0)


def test_feature_range_rejects_nan_support_bounds() -> None:
    from korpus.application.controller_profile import FeatureRange, RuleCondition

    with pytest.raises(ValueError, match="finite"):
        FeatureRange(minimum=math.nan)
    with pytest.raises(ValueError, match="finite"):
        RuleCondition(feature="top1_score", operator="gt", value=math.nan)


def test_canary_policy_cannot_be_weakened_by_invalid_numeric_types() -> None:
    from korpus.application.pec_canary_admission import evaluate_canary
    from korpus.application.pec_revision_binding import RevisionBinding

    binding = RevisionBinding("v0.9.7", "rev", "profile", "CANARY", "PRODUCTION", "a" * 64)
    receipt = {
        "release": "v0.9.7", "cloud_run_revision": "rev-1", "environment_class": "PRODUCTION",
        "samples": 100, "server_error_rate": 0.0, "human_judgment_admissible": True,
    }
    with pytest.raises(ValueError, match="minimum_samples"):
        evaluate_canary(receipt, binding=binding, cloud_run_revision="rev-1", minimum_samples=-1, maximum_server_error_rate=0.01)
    with pytest.raises(ValueError, match="maximum_server_error_rate"):
        evaluate_canary(receipt, binding=binding, cloud_run_revision="rev-1", minimum_samples=1, maximum_server_error_rate=math.nan)


def test_metamorphic_gate_rejects_string_boolean_and_fractional_rank() -> None:
    from korpus.application.pec_metamorphic_rules import metamorphic_issues

    base = {"authorization_decision": "ALLOW", "risk_rank": 2, "authority_rank": 2, "gold_retrievable": True, "answer_status": "answered"}
    transformed = {
        "semantics_validated": "false", "authorization_decision": "ALLOW", "risk_rank": 1.5,
        "authority_rank": 2, "gold_retrievable": True, "citations_source_bound": "true",
        "planner_permission_expanded": "false", "answer_status": "answered",
    }
    issues = metamorphic_issues(base, transformed)
    assert "transformation_not_semantically_validated" in issues
    assert "invalid_risk_rank" in issues
    assert "citation_source_binding_failed" in issues
    assert "invalid_planner_permission" in issues


def test_audit_sequence_rejects_fractional_and_string_coercion() -> None:
    from korpus.application.pec_audit_trace import extract_audit_trace
    from korpus.application.pec_revision_binding import RevisionBinding

    binding = RevisionBinding("v0.9.7", "rev", "profile", "CANARY", "PRODUCTION", "a" * 64)
    base = {"event_id": "e", "revision": "rev", "profile": "profile", "phase": "CANARY", "environment_class": "PRODUCTION", "action": "x"}
    for bad in (1.5, "1", True):
        with pytest.raises(ValueError, match="sequence"):
            extract_audit_trace([{**base, "sequence": bad}], binding)


def test_replay_priority_rejects_string_booleans_and_nan_residual() -> None:
    from korpus.application.pec_replay import replay_priority

    with pytest.raises(ValueError, match="accepted_answer_error"):
        replay_priority({"accepted_answer_error": "false"})
    with pytest.raises(ValueError, match="retrieval_benefit_residual"):
        replay_priority({"retrieval_benefit_residual": math.nan})


def test_information_gain_refuses_boolean_and_count_coercion() -> None:
    from korpus.application.pec_research import observed_information_gain

    rows = [
        {"query_id": "q", "action": "STOP_USE_CURRENT_EVIDENCE", "gold_hit": False, "quality_ok": False, "search_count": 1},
        {"query_id": "q", "action": "EXPAND", "gold_hit": "true", "quality_ok": True, "search_count": "2"},
    ]
    with pytest.raises(ValueError):
        observed_information_gain(rows)


def _load_script_module(name: str):
    import importlib.util
    import sys
    from pathlib import Path

    script_dir = Path(__file__).resolve().parents[3] / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    path = script_dir / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_controller_export_refuses_semantic_type_coercion() -> None:
    module = _load_script_module("pec_controller_export_impl")
    training = {
        "leaves": [
            {
                "leaf_id": "x",
                "conditions": [],
                "action": "STOP_USE_CURRENT_EVIDENCE",
                "admitted": "false",
                "calibration_samples": 100,
                "upper_error_bound": 0.01,
                "support": {},
            }
        ]
    }
    with pytest.raises(ValueError, match="admitted must be boolean"):
        module._rules(training)

    training["leaves"][0]["admitted"] = False
    training["leaves"][0]["calibration_samples"] = 1.5
    with pytest.raises(ValueError, match="calibration_samples"):
        module._rules(training)


def test_controller_export_requires_open_unit_risk_limit() -> None:
    module = _load_script_module("pec_controller_export_impl")
    for bad in (math.nan, 0.0, 1.0, True, "0.5"):
        with pytest.raises(ValueError):
            module._strict_open_unit_rate(bad, label="controller_risk_limit")


def test_training_argument_gate_rejects_nan_and_invalid_count() -> None:
    import argparse

    module = _load_script_module("pec_controller_training_impl")
    with pytest.raises(ValueError, match="delta"):
        module._validate_arguments(argparse.Namespace(delta=math.nan, risk_limit=0.1, minimum_leaf_samples=30))
    with pytest.raises(ValueError, match="risk-limit"):
        module._validate_arguments(argparse.Namespace(delta=0.05, risk_limit=1.0, minimum_leaf_samples=30))
    with pytest.raises(ValueError, match="minimum-leaf-samples"):
        module._validate_arguments(argparse.Namespace(delta=0.05, risk_limit=0.1, minimum_leaf_samples=True))


def test_training_support_and_candidates_reject_nonfinite_features() -> None:
    from korpus.application import pec_training_model as tm

    module = _load_script_module("pec_controller_training_impl")
    with pytest.raises(ValueError, match="must be finite"):
        module._update_support({}, {"top1_score": math.nan})

    rows = [
        tm.TrainingRow("q1", "g1", {"top1_score": 0.1}, "A"),
        tm.TrainingRow("q2", "g2", {"top1_score": math.inf}, "B"),
    ]
    with pytest.raises(ValueError, match="must be finite"):
        list(tm._candidates(rows))


def test_training_tree_hyperparameters_are_strict_counts() -> None:
    from korpus.application import pec_training_model as tm

    rows = [tm.TrainingRow("q", "g", {"top1_score": 0.1}, "A")]
    with pytest.raises(ValueError, match="max_depth"):
        tm.train_tree(rows, max_depth=True, min_leaf=1)
    with pytest.raises(ValueError, match="min_leaf"):
        tm.train_tree(rows, max_depth=1, min_leaf=0)


def test_ablation_rejects_nonfinite_resources_and_boolean_pair_count() -> None:
    from korpus.application.pec_ablation import compare_ablation

    base = {"q": {"authorization_ok": True, "answer_error": False, "quality_ok": True,
                   "latency_ms": 1.0, "search_count": 1, "planner_calls": 0,
                   "semantic_calls": 0, "candidate_count": 1, "external_tokens": 0,
                   "provider_cost_microunits": 0}}
    candidate = {"q": dict(base["q"])}
    candidate["q"]["latency_ms"] = math.nan
    with pytest.raises(ValueError, match="finite numeric"):
        compare_ablation(base, candidate, minimum_pairs=1)
    with pytest.raises(ValueError, match="minimum_pairs"):
        compare_ablation(base, base, minimum_pairs=True)


def test_contextual_benchmark_rejects_coerced_flags_and_fractional_rank() -> None:
    from korpus.application.pec_contextual_benchmark import evaluate_contextual_benchmark

    row = {
        "query_id": "q", "baseline_hit": "false", "baseline_rank": None,
        "contextual_hit": False, "contextual_rank": None,
        "evidence_unchanged": True, "citations_source_bound": True,
    }
    report = evaluate_contextual_benchmark([row], minimum_informative_pairs=1)
    assert report["status"] == "FAIL"
    assert any(str(issue).startswith("invalid_boolean:q:") for issue in report["issues"])

    row.update({"baseline_hit": True, "baseline_rank": 1.5, "contextual_hit": True, "contextual_rank": 1})
    with pytest.raises(ValueError, match="positive integer"):
        evaluate_contextual_benchmark([row], minimum_informative_pairs=1)


def test_human_judgment_requires_explicit_boolean_model_flag() -> None:
    from korpus.application.pec_human_judgment import evaluate_human_judgments
    from korpus.application.pec_revision_binding import RevisionBinding

    binding = RevisionBinding("v0.9.7", "rev", "profile", "CANARY", "PRODUCTION", "a" * 64)
    row = {"case_id": "c", "actor_type": "HUMAN", "revision": "rev", "profile": "profile",
           "phase": "CANARY", "judgment_provenance_sha256": "b" * 64}
    verdict = evaluate_human_judgments([row], expected_case_ids=["c"], binding=binding)
    assert not verdict.admissible
    assert "invalid_model_self_judgment:c" in verdict.failures


def test_research_statistical_controls_reject_invalid_domains() -> None:
    from korpus.application.pec_research import conditional_risk_report, replay_priority_enrichment

    with pytest.raises(ValueError, match="delta"):
        conditional_risk_report([], stratum_key="s", error_key="e", risk_limit=0.1,
                                delta=math.nan, minimum_samples=1)
    with pytest.raises(ValueError, match="minimum_samples"):
        conditional_risk_report([], stratum_key="s", error_key="e", risk_limit=0.1,
                                delta=0.05, minimum_samples=True)
    with pytest.raises(ValueError, match="alpha"):
        replay_priority_enrichment([], alpha=math.nan)
