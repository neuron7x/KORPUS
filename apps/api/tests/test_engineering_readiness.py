from __future__ import annotations

from copy import deepcopy

import pytest

from korpus.application.engineering_readiness import evaluate_engineering_profile

SOURCE = "a" * 64
RELEASE = "v0.7.0"


def profile() -> dict:
    return {
        "profile_id": "test",
        "target_percent": 87.0,
        "dimensions": {
            "a": {"weight": 0.6, "evidence_class": "EXECUTED_WITH_NEGATIVE_CONTROL", "criteria": ["a1", "a2"]},
            "b": {"weight": 0.4, "evidence_class": "EXECUTED", "criteria": ["b1", "b2"]},
        },
        "hard_external_predicates": ["b2"],
    }


def evidence() -> dict:
    return {
        "dimensions": {
            "a": {"status": "PASS", "source_tree_sha256": SOURCE, "release": RELEASE, "criteria": {"a1": True, "a2": True}},
            "b": {"status": "PASS", "source_tree_sha256": SOURCE, "release": RELEASE, "criteria": {"b1": True, "b2": False}},
        }
    }


def test_score_is_weighted_and_evidence_capped() -> None:
    result = evaluate_engineering_profile(profile(), evidence(), source_digest=SOURCE, release=RELEASE)
    assert result["dimensions"]["a"]["calibrated_percent"] == 97.0
    assert result["dimensions"]["b"]["raw_percent"] == 50.0
    assert result["engineering_readiness_percent"] == 78.2
    assert not result["target_met"]
    assert result["external_or_tooling_gaps"] == ["b2"]
    assert result["production_authorized_by_score"] is False


def test_missing_criterion_is_zero_not_skip() -> None:
    payload = evidence()
    del payload["dimensions"]["a"]["criteria"]["a2"]
    result = evaluate_engineering_profile(profile(), payload, source_digest=SOURCE, release=RELEASE)
    assert result["dimensions"]["a"]["passed"] == 1
    assert result["dimensions"]["a"]["total"] == 2


def test_stale_source_zeroes_dimension() -> None:
    payload = evidence()
    payload["dimensions"]["a"]["source_tree_sha256"] = "b" * 64
    result = evaluate_engineering_profile(profile(), payload, source_digest=SOURCE, release=RELEASE)
    assert result["dimensions"]["a"]["calibrated_percent"] == 0.0


def test_unknown_criterion_is_rejected() -> None:
    payload = evidence()
    payload["dimensions"]["a"]["criteria"]["invented"] = True
    with pytest.raises(ValueError, match="unknown criteria"):
        evaluate_engineering_profile(profile(), payload, source_digest=SOURCE, release=RELEASE)


def test_target_score_never_authorizes_production() -> None:
    payload = evidence()
    payload["dimensions"]["b"]["criteria"]["b2"] = True
    result = evaluate_engineering_profile(profile(), payload, source_digest=SOURCE, release=RELEASE)
    assert result["engineering_readiness_percent"] >= 87.0
    assert result["target_met"]
    assert result["production_authorized_by_score"] is False


def test_invalid_evidence_class_is_rejected() -> None:
    payload = deepcopy(evidence())
    payload["dimensions"]["a"]["evidence_class"] = "MAGIC"
    with pytest.raises(ValueError, match="unknown evidence class"):
        evaluate_engineering_profile(profile(), payload, source_digest=SOURCE, release=RELEASE)
