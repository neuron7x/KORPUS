from __future__ import annotations

from korpus.application.controller_profile import ControllerLeaf, ControllerProfile, ControllerRule
from korpus.application.evidence_state import feature_schema_sha256
from korpus.application.pec_ablation import compare_ablation
from korpus.application.pec_metamorphic import metamorphic_issues
from korpus.application.pec_promotion import REQUIRED_RECEIPTS, promotion_errors

RESOURCE_FIELDS = (
    "latency_ms",
    "search_count",
    "planner_calls",
    "semantic_calls",
    "candidate_count",
    "external_tokens",
    "provider_cost_microunits",
)


def _row(*, latency: float, quality: bool = True, auth: bool = True, error: bool = False):
    row = {
        "authorization_ok": auth,
        "answer_error": error,
        "quality_ok": quality,
        "latency_ms": latency,
        "search_count": 1,
        "planner_calls": 0,
        "semantic_calls": 0,
        "candidate_count": 8,
        "external_tokens": 0,
        "provider_cost_microunits": 0,
    }
    assert set(RESOURCE_FIELDS) <= set(row)
    return row


def test_ablation_requires_confidence_supported_resource_superiority() -> None:
    baseline = {f"q{index}": _row(latency=10.0) for index in range(30)}
    candidate = {f"q{index}": _row(latency=5.0) for index in range(30)}
    result = compare_ablation(baseline, candidate, minimum_pairs=20)
    assert result["status"] == "PASS"
    assert result["safety_regressions"] == 0
    assert result["quality_regressions"] == 0
    assert result["resources"]["latency_ms"]["confidence_supported_improvement"] is True


def test_ablation_fails_before_efficiency_when_quality_regresses() -> None:
    baseline = {f"q{index}": _row(latency=10.0) for index in range(30)}
    candidate = {f"q{index}": _row(latency=5.0, quality=index != 0) for index in range(30)}
    result = compare_ablation(baseline, candidate, minimum_pairs=20)
    assert result["status"] == "FAIL"
    assert result["quality_regressions"] == 1


def _metamorphic_base() -> dict[str, object]:
    return {
        "authorization_decision": "ALLOW",
        "risk_rank": 2,
        "authority_rank": 4,
        "gold_retrievable": True,
        "answer_status": "answered",
        "source_digest": "1" * 64,
        "corpus_release_id": "a" * 16,
        "evaluation_protocol_sha256": "2" * 64,
        "answer_calibration_id": "cal-test",
    }


def _metamorphic_transform() -> dict[str, object]:
    return {
        "semantics_validated": True,
        "authorization_decision": "ALLOW",
        "risk_rank": 2,
        "authority_rank": 4,
        "gold_retrievable": True,
        "citations_source_bound": True,
        "planner_permission_expanded": False,
        "answer_status": "answered",
        "source_digest": "1" * 64,
        "corpus_release_id": "a" * 16,
        "evaluation_protocol_sha256": "2" * 64,
        "answer_calibration_id": "cal-test",
    }


def test_metamorphic_invariant_accepts_semantics_preserving_equivalent_transition() -> None:
    assert metamorphic_issues(_metamorphic_base(), _metamorphic_transform()) == []


def test_metamorphic_invariant_kills_risk_weakening_and_source_unbinding() -> None:
    transformed = _metamorphic_transform()
    transformed["risk_rank"] = 1
    transformed["citations_source_bound"] = False
    issues = metamorphic_issues(_metamorphic_base(), transformed)
    assert "risk_class_weakened" in issues
    assert "citation_source_binding_failed" in issues


def test_ablation_without_supported_efficiency_gain_remains_unknown():
    baseline = {f"q{index}": _row(latency=10.0) for index in range(30)}
    candidate = {f"q{index}": _row(latency=10.0) for index in range(30)}
    result = compare_ablation(baseline, candidate, minimum_pairs=20)
    assert result["status"] == "UNKNOWN"
    assert result["confidence_supported_efficiency_improvement"] is False


def _admitted_profile() -> ControllerProfile:
    return ControllerProfile(
        profile_id="pec-promotion-test",
        dataset_sha256="1" * 64,
        system_manifest_sha256="2" * 64,
        evaluation_protocol_sha256="3" * 64,
        replay_receipt_sha256="4" * 64,
        training_receipt_sha256="5" * 64,
        feature_schema_sha256=feature_schema_sha256(),
        corpus_release_id="a" * 16,
        answer_calibration_id="cal-test",
        admission_status="PASS",
        controller_risk_limit=0.05,
        minimum_leaf_samples=1,
        rules=(
            ControllerRule(
                rule_id="r",
                leaf=ControllerLeaf(
                    leaf_id="l",
                    action="STOP_USE_CURRENT_EVIDENCE",
                    admitted=True,
                    observed_samples=1,
                    upper_error_bound=0.0,
                ),
            ),
        ),
    )


def test_promotion_refuses_any_nonpass_required_receipt():
    statuses = {name: "PASS" for name in REQUIRED_RECEIPTS}
    statuses["metamorphic"] = "UNKNOWN"
    errors = promotion_errors(_admitted_profile(), statuses)
    assert any(error.startswith("nonpass_receipts:") for error in errors)


def test_promotion_accepts_only_complete_pass_evidence_set():
    statuses = {name: "PASS" for name in REQUIRED_RECEIPTS}
    assert promotion_errors(_admitted_profile(), statuses) == []


def test_promotion_rejects_green_but_cross_run_evidence_chain() -> None:
    from korpus.application.pec_promotion import promotion_binding_errors

    profile = _admitted_profile()
    digests = {
        "counterfactual_replay": profile.replay_receipt_sha256,
        "oracle": "6" * 64,
        "training": profile.training_receipt_sha256,
    }
    receipts = {
        "dataset_audit": {"dataset_sha256": profile.dataset_sha256},
        "counterfactual_replay": {
            "dataset_sha256": profile.dataset_sha256,
            "corpus_release_id": profile.corpus_release_id,
            "evaluation_protocol_sha256": profile.evaluation_protocol_sha256,
            "answer_calibration_id": profile.answer_calibration_id,
        },
        "oracle": {"replay_sha256": "f" * 64},
        "training": {
            "dataset_sha256": profile.dataset_sha256,
            "oracle_sha256": digests["oracle"],
        },
        "controller_verify": {"profile_sha256": "7" * 64},
        "ablation": {
            "binding": {
                "dataset_sha256": profile.dataset_sha256,
                "corpus_release_id": profile.corpus_release_id,
                "evaluation_protocol_sha256": profile.evaluation_protocol_sha256,
                "answer_calibration_id": profile.answer_calibration_id,
            }
        },
        "metamorphic": {
            "binding": {
                "source_digest": "8" * 64,
                "corpus_release_id": profile.corpus_release_id,
                "evaluation_protocol_sha256": profile.evaluation_protocol_sha256,
                "answer_calibration_id": profile.answer_calibration_id,
            }
        },
    }
    errors = promotion_binding_errors(profile, receipts, digests, profile_file_sha256="9" * 64)
    assert "binding_mismatch:oracle:replay_sha256" in errors
    assert "binding_mismatch:controller_verify:profile_sha256" in errors
