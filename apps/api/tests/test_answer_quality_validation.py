"""Counts and complete dataset identities must support every compared rate."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from .test_answer_quality_ratchet import CONFIG, GOOD

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from answer_quality_validation import finite_rate  # noqa: E402
from check_answer_quality_ratchet import problems, selftest  # noqa: E402


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        -float("inf"),
        -0.1,
        1.1,
        True,
        False,
        "0.95",
        None,
        [],
        {},
        10**1000,
    ],
)
def test_rates_outside_finite_probability_domain_are_refused(value: object) -> None:
    assert finite_rate(value) is False
    for stratum in ("in_corpus", "out_of_corpus"):
        report = copy.deepcopy(GOOD)
        report[stratum]["rate"] = value
        assert problems(report, CONFIG)


def test_nonfinite_floor_is_rejected_before_comparison() -> None:
    config = copy.deepcopy(CONFIG)
    config["floors"]["in_corpus_answered_rate"] = float("nan")
    # A comparison with NaN is false, so threshold comparison alone would PASS.
    assert problems(GOOD, config)


@pytest.mark.parametrize(
    "section,axis",
    [
        ("floors", "in_corpus_answered_rate"),
        ("ceilings", "out_of_corpus_answered_rate"),
        ("measured", "in_corpus_answered_rate"),
        ("measured", "out_of_corpus_answered_rate"),
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 2, True, "0.9", None])
def test_every_policy_rate_is_validated(section: str, axis: str, value: object) -> None:
    config = copy.deepcopy(CONFIG)
    config[section][axis] = value
    assert problems(GOOD, config)


@pytest.mark.parametrize(
    "field,value",
    [
        ("answered", -1),
        ("answered", 21),
        ("answered", True),
        ("answered", 19.0),
        ("judged", 0),
        ("judged", -1),
        ("judged", True),
        ("judged", 20.0),
        ("judged", "20"),
        ("rate", 0.9),
    ],
)
def test_counts_are_positive_integers_and_reproduce_the_exact_rate(
    field: str, value: object
) -> None:
    report = copy.deepcopy(GOOD)
    report["in_corpus"][field] = value
    assert problems(report, CONFIG)


def test_empty_measured_denominator_is_not_zero_success() -> None:
    report = {**GOOD, "in_corpus": {"answered": 0, "judged": 0, "rate": 0}}
    assert problems(report, CONFIG)


@pytest.mark.parametrize("stratum", ["in_corpus", "out_of_corpus"])
def test_missing_counts_cannot_be_replaced_by_a_plausible_rate(stratum: str) -> None:
    for bucket in (None, {"rate": GOOD[stratum]["rate"]}):
        assert problems({**GOOD, stratum: bucket}, CONFIG)


def test_digest_suffix_cannot_be_replaced_under_matching_prefix() -> None:
    digest = GOOD["set_digest"]
    changed = digest[:16] + ("a" * 48 if digest[16:] != "a" * 48 else "b" * 48)
    assert problems({**GOOD, "set_digest": changed}, CONFIG)
    for short in (digest[:16], "", None, True):
        assert problems({**GOOD, "set_digest": short}, CONFIG)


@pytest.mark.parametrize(
    "section,value",
    [
        ("floors", []),
        ("floors", {}),
        ("ceilings", None),
        ("measured", []),
        ("measured", {"set_digest": "a" * 16}),
        ("relaxed", {}),
        ("relaxed", [None]),
        ("relaxed", [{"axis": "unknown", "reason": "A sufficiently long explanation"}]),
        ("relaxed", [{"axis": "in_corpus_answered_rate", "reason": 1000}]),
    ],
)
def test_malformed_policy_objects_are_refused(section: str, value: object) -> None:
    assert problems(GOOD, {**CONFIG, section: value})


def test_nonobject_report_and_hidden_unavailable_rows_are_refused() -> None:
    assert problems([], CONFIG)
    assert problems(GOOD, [])
    assert problems({**GOOD, "unreachable": ["missing"]}, CONFIG)
    assert problems({**GOOD, "invalid": ["bad-response"]}, CONFIG)


def test_exact_zero_one_and_fraction_controls_remain_accepted() -> None:
    config = copy.deepcopy(CONFIG)
    config["floors"]["in_corpus_answered_rate"] = 0
    config["ceilings"]["out_of_corpus_answered_rate"] = 1
    for answered, judged in ((0, 1), (1, 1), (2, 3)):
        bucket = {"answered": answered, "judged": judged, "rate": answered / judged}
        report = {**GOOD, "in_corpus": bucket, "out_of_corpus": bucket}
        assert problems(report, config) == []
    assert problems(GOOD, CONFIG) == []
    assert selftest() == 0


def test_recorded_baseline_retains_rates_and_full_existing_dataset_identity() -> None:
    config = json.loads((ROOT / "config/operations/answer-quality-ratchet.json").read_text())
    meta = json.loads((ROOT / "evals/datasets/domain_boundary.meta.json").read_text())
    assert config["measured"]["set_digest"] == meta["digest"]
    assert config["measured"]["in_corpus_answered_rate"] == 0.95
    assert config["measured"]["out_of_corpus_answered_rate"] == 0.2
    assert problems(GOOD, config) == []
