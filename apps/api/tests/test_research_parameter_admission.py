"""Parameter admission in the research pipeline: what a statistic refuses to compute.

`conditional_risk_report`, `replay_priority_enrichment`, `observed_information_gain` and
`production_judgment_validity` each produce a number a promotion decision reads. Measured
on 2026-08-28 the module sat at 89.7% branch coverage with every refusal untaken — the
functions had only been called with parameters that were already valid.

A statistic computed from an inadmissible parameter is worse than no statistic. A delta
of 0 asks for a bound that holds with certainty from finite data; a top fraction above 1
selects more rows than exist; a non-boolean `production_judged` counts as judged under
truthiness. All three produce a number, and none of the numbers mean what the caller
believes.
"""

from __future__ import annotations

import pytest
from korpus.application.pec_research import (
    conditional_risk_report,
    observed_information_gain,
    production_judgment_validity,
    replay_priority_enrichment,
)


def _risk_report(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "stratum_key": "group",
        "error_key": "failed",
        "risk_limit": 0.05,
        "delta": 0.05,
        "minimum_samples": 30,
    }
    values.update(changes)
    return conditional_risk_report([], **values)  # type: ignore[arg-type]


@pytest.mark.parametrize("delta", [0.0, 1.0])
def test_a_confidence_parameter_at_the_closed_ends_is_refused(delta: float) -> None:
    """`delta` is the failure probability of the bound; 0 claims certainty from finite data.

    At 1 the bound holds vacuously and reports nothing. Both ends produce a number that
    reads like a risk statement and is not one.
    """
    with pytest.raises(ValueError, match="delta must be strictly inside"):
        _risk_report(delta=delta)


@pytest.mark.parametrize("delta", [-0.1, 1.5, float("nan"), float("inf")])
def test_a_confidence_parameter_that_is_not_a_rate_at_all_is_refused(delta: float) -> None:
    """Outside [0, 1] the rate contract rejects it before the open-interval check runs."""
    with pytest.raises(ValueError, match="delta must be finite and in"):
        _risk_report(delta=delta)


@pytest.mark.parametrize("risk_limit", [-0.1, 1.5, float("nan"), float("inf")])
def test_a_risk_limit_that_is_not_a_rate_is_refused(risk_limit: float) -> None:
    """A risk limit outside [0, 1] is not a probability, and NaN compares false to every
    bound it is later tested against."""
    with pytest.raises(ValueError, match="risk_limit"):
        _risk_report(risk_limit=risk_limit)


@pytest.mark.parametrize("minimum_samples", [0, -1, 1.5, None])
def test_a_non_positive_sample_minimum_is_refused(minimum_samples: object) -> None:
    """A group admitted on zero samples is admitted on no evidence."""
    with pytest.raises(ValueError, match="minimum_samples"):
        _risk_report(minimum_samples=minimum_samples)


@pytest.mark.parametrize("fraction", [0.0, 1.5, -0.2, float("nan"), float("inf")])
def test_a_top_fraction_outside_its_range_is_reported_as_unknown_not_computed(
    fraction: float,
) -> None:
    """Unlike the parameters above this one answers UNKNOWN rather than raising.

    The distinction is deliberate: an out-of-range fraction is a caller error the pipeline
    can report and continue past, while an inadmissible confidence parameter would make
    every downstream number meaningless.
    """
    # Rows are supplied on purpose: with an empty list the function answers UNKNOWN for
    # a different reason, and the fraction check would be indistinguishable from absent.
    rows = [
        {"query_id": f"q{index}", "priority": index, "failed": index % 2 == 0}
        for index in range(10)
    ]
    result = replay_priority_enrichment(rows, top_fraction=fraction, alpha=0.05)
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == "insufficient_rows_or_fraction"


def test_a_significance_level_of_zero_is_refused() -> None:
    """Alpha 0 demands a test that never rejects; the interval is half-open on purpose."""
    with pytest.raises(ValueError, match="alpha must be inside"):
        replay_priority_enrichment([], top_fraction=0.2, alpha=0.0)


@pytest.mark.parametrize("alpha", [-0.1, 1.5, float("nan")])
def test_a_significance_level_that_is_not_a_rate_is_refused(alpha: float) -> None:
    with pytest.raises(ValueError, match="alpha must be finite and in"):
        replay_priority_enrichment([], top_fraction=0.2, alpha=alpha)


def test_no_rows_is_unknown_rather_than_a_result() -> None:
    """Zero rows and a valid fraction is still nothing to rank."""
    result = replay_priority_enrichment([], top_fraction=0.2, alpha=0.05)
    assert result["status"] == "UNKNOWN"


def test_a_non_boolean_production_judged_flag_is_recorded_as_invalid() -> None:
    """Truthiness would count the string "no" as a completed human judgment.

    The row is reported by id rather than dropped, so the count of judgments and the
    count of rows that could not be read are both visible to the caller.
    """
    result = production_judgment_validity(
        [
            {"id": "r1", "production_judged": True, "judgment": "correct"},
            {"id": "r2", "production_judged": "no"},
            {"id": "r3", "production_judged": 1},
            {"id": "r4", "production_judged": None},
        ]
    )
    invalid = result.get("invalid")
    assert isinstance(invalid, list)
    assert {
        "invalid_production_judged:r2",
        "invalid_production_judged:r3",
        "invalid_production_judged:r4",
    } <= set(invalid)


def test_an_unusable_information_gain_input_is_unknown_rather_than_zero() -> None:
    """Zero gain is a measurement; UNKNOWN is the absence of one, and they differ."""
    result = observed_information_gain([])
    assert result["status"] == "UNKNOWN"
