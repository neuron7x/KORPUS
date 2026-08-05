"""A fixture run must not be able to present itself as a measurement.

`calibration_status` was the constant `UNVALIDATED_TEST_FIXTURE` written into the eval
report. It said the right thing, and it would have said exactly the same thing about a
run on a real corpus: nothing distinguished "we know this is a fixture" from "nobody
asked". §2.6 of the admission boundary is that gap.

Two properties are stated. A run is a fixture run unless the *dataset* declares a real
corpus — identifier, owner, digest of the document set — so the harness cannot promote
one by flipping a flag. And a point estimate is reported with the interval it actually
supports: 30/30 is not 1.0, it is "above 0.886 with 95% confidence", and a run whose
interval is wider than policy allows is not admissible however good the estimate looks.
"""

from __future__ import annotations

from typing import Any

import pytest
from korpus.application.tevv import (
    FIXTURE_STATUS,
    MEASURED_STATUS,
    evaluate_tevv,
    wilson_interval,
)

REAL_CORPUS: dict[str, Any] = {
    "record": "corpus",
    "corpus_id": "unit-orders-2026",
    "owner": "Authorized Corpus Owner",
    "document_set_sha256": "c" * 64,
}


def test_a_perfect_score_is_not_certainty() -> None:
    """The normal approximation collapses to [1.0, 1.0]; thirty observations do not."""
    interval = wilson_interval(30, 30)

    assert interval.upper == 1.0
    assert 0.85 < interval.lower < 0.90
    assert interval.width > 0.1


def test_more_observations_narrow_the_interval() -> None:
    assert wilson_interval(500, 500).width < wilson_interval(30, 30).width


def test_the_shipped_fixture_run_is_not_admissible() -> None:
    """The current state, stated as a test so it cannot drift silently."""
    verdict = evaluate_tevv(
        passed=30,
        total=30,
        corpus_declaration=None,
        maximum_interval_width=0.10,
        minimum_observations=200,
    )

    assert verdict.admissible is False
    assert verdict.calibration_status == FIXTURE_STATUS
    assert any("fixture run" in reason for reason in verdict.reasons)
    assert any("below the floor" in reason for reason in verdict.reasons)


def test_a_declared_corpus_with_enough_observations_is_admissible() -> None:
    """The mechanism has to be able to say yes, or it decides nothing."""
    verdict = evaluate_tevv(
        passed=980,
        total=1000,
        corpus_declaration=REAL_CORPUS,
        maximum_interval_width=0.10,
        minimum_observations=200,
    )

    assert verdict.admissible is True, verdict.reasons
    assert verdict.calibration_status == MEASURED_STATUS


@pytest.mark.parametrize("field", ["corpus_id", "owner", "document_set_sha256"])
def test_an_incomplete_corpus_declaration_is_refused(field: str) -> None:
    declaration = dict(REAL_CORPUS)
    declaration.pop(field)

    verdict = evaluate_tevv(
        passed=980,
        total=1000,
        corpus_declaration=declaration,
        maximum_interval_width=0.10,
        minimum_observations=200,
    )

    assert verdict.admissible is False
    assert verdict.calibration_status == FIXTURE_STATUS
    assert any(field in reason for reason in verdict.reasons), verdict.reasons


def test_a_corpus_that_declares_itself_synthetic_is_refused() -> None:
    verdict = evaluate_tevv(
        passed=980,
        total=1000,
        corpus_declaration=REAL_CORPUS | {"synthetic": True},
        maximum_interval_width=0.10,
        minimum_observations=200,
    )

    assert verdict.admissible is False
    assert any("synthetic" in reason for reason in verdict.reasons)


def test_a_wide_interval_is_refused_even_on_a_real_corpus() -> None:
    """Enough rows to clear the floor, not enough agreement to constrain the answer."""
    verdict = evaluate_tevv(
        passed=150,
        total=250,
        corpus_declaration=REAL_CORPUS,
        maximum_interval_width=0.10,
        minimum_observations=200,
    )

    assert verdict.admissible is False
    assert any("interval" in reason for reason in verdict.reasons), verdict.reasons


def test_the_eval_report_carries_the_verdict_and_the_interval() -> None:
    """Read from the shipped report: the field must survive the harness, not just exist."""
    import json
    from pathlib import Path

    report_path = Path("var/eval-report.json")
    if not report_path.is_file():
        pytest.skip("var/eval-report.json is produced by scripts/run_evals.py")
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["calibration_status"] == report["tevv"]["calibration_status"]
    assert report["tevv"]["pass_rate_interval"]["width"] > 0
