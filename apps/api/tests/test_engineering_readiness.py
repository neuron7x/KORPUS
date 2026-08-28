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
            "a": {
                "weight": 0.6,
                "evidence_class": "EXECUTED_WITH_NEGATIVE_CONTROL",
                "criteria": ["a1", "a2"],
            },
            "b": {"weight": 0.4, "evidence_class": "EXECUTED", "criteria": ["b1", "b2"]},
        },
        "hard_external_predicates": ["b2"],
    }


def evidence() -> dict:
    return {
        "dimensions": {
            "a": {
                "status": "PASS",
                "source_tree_sha256": SOURCE,
                "release": RELEASE,
                "criteria": {"a1": True, "a2": True},
            },
            "b": {
                "status": "PASS",
                "source_tree_sha256": SOURCE,
                "release": RELEASE,
                "criteria": {"b1": True, "b2": False},
            },
        }
    }


def test_score_is_weighted_and_evidence_capped() -> None:
    result = evaluate_engineering_profile(
        profile(), evidence(), source_digest=SOURCE, release=RELEASE
    )
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


def _evaluate(profile_doc: dict, evidence_doc: dict) -> dict:
    return evaluate_engineering_profile(
        profile_doc, evidence_doc, source_digest=SOURCE, release=RELEASE
    )


@pytest.mark.parametrize("criteria", [[], ["a1", "a1"], ["a1", "a2", "a1"]])
def test_a_dimension_whose_criteria_are_empty_or_repeated_is_refused(criteria: list) -> None:
    """The count of criteria is the denominator of the dimension's score.

    An empty list divides by zero; a repeated id counts one result twice, so a dimension
    with two real criteria and one duplicate reports three-thirds from two passes.
    """
    doc = profile()
    doc["dimensions"]["a"]["criteria"] = criteria
    with pytest.raises(ValueError, match="criteria must be non-empty and unique"):
        _evaluate(doc, evidence())


@pytest.mark.parametrize("results", ["a1", ["a1"], 7, None])
def test_criterion_results_that_are_not_an_object_are_refused(results: object) -> None:
    """A list of ids says which criteria exist, not which of them passed."""
    ev = evidence()
    ev["dimensions"]["a"]["criteria"] = results
    with pytest.raises(ValueError, match="criterion results must be an object"):
        _evaluate(profile(), ev)


def test_evidence_naming_a_criterion_the_profile_does_not_declare_is_refused() -> None:
    """The profile is preregistered; evidence may not extend it after the fact.

    Silently ignoring an unknown id would let a run report results for criteria nobody
    committed to in advance, which is the shape of a moved goalpost.
    """
    ev = evidence()
    ev["dimensions"]["a"]["criteria"]["a3_invented_later"] = True
    with pytest.raises(ValueError, match="unknown criteria"):
        _evaluate(profile(), ev)


def test_evidence_naming_a_dimension_the_profile_does_not_declare_is_refused() -> None:
    ev = evidence()
    ev["dimensions"]["c_invented_later"] = {"criteria": {}}
    with pytest.raises(ValueError, match="unknown evidence dimensions"):
        _evaluate(profile(), ev)


@pytest.mark.parametrize("payload", ["dimensions", ["a"], 3, None])
def test_a_profile_or_evidence_without_dimension_mappings_is_refused(payload: object) -> None:
    doc = profile()
    doc["dimensions"] = payload
    with pytest.raises(ValueError, match="require dimension mappings"):
        _evaluate(doc, evidence())

    ev = evidence()
    ev["dimensions"] = payload
    with pytest.raises(ValueError, match="require dimension mappings"):
        _evaluate(profile(), ev)


@pytest.mark.parametrize("policy", ["0.6", ["weight"], 0.6, None])
def test_a_dimension_policy_that_is_not_an_object_is_refused(policy: object) -> None:
    doc = profile()
    doc["dimensions"]["a"] = policy
    with pytest.raises(ValueError, match="policy must be an object"):
        _evaluate(doc, evidence())


@pytest.mark.parametrize("raw", ["{}", ["a1"], 1, True])
def test_dimension_evidence_that_is_not_an_object_is_refused(raw: object) -> None:
    ev = evidence()
    ev["dimensions"]["a"] = raw
    with pytest.raises(ValueError, match="evidence must be an object"):
        _evaluate(profile(), ev)
