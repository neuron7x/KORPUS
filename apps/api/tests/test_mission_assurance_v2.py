from __future__ import annotations

import pytest
from korpus.application.mission_assurance_v2 import (
    HardFailure,
    MissionObservation,
    evaluate_mission_assurance,
)


def _rows(n: int):
    return [
        MissionObservation(
            case_id=f"c{i}", atomic_claims=2, correct_atomic_claims=2, latency_ms=float(i % 20)
        )
        for i in range(n)
    ]


def test_zero_observed_failures_is_not_zero_risk_or_automatic_admission():
    verdict = evaluate_mission_assurance(
        _rows(30),
        minimum_cases=400,
        maximum_hard_failure_rate_upper_95=0.01,
        independent=True,
        real_domain=True,
        operational_environment=True,
    )
    assert not verdict.admissible
    assert verdict.hard_failure_count == 0
    assert verdict.hard_failure_interval.upper > 0.01


def test_one_hard_failure_cannot_be_compensated_by_perfect_claim_accuracy():
    rows = _rows(500)
    rows[0] = MissionObservation(
        case_id="bad",
        hard_failures=frozenset({HardFailure.ACCESS_LEAKAGE}),
        atomic_claims=1000,
        correct_atomic_claims=1000,
        latency_ms=1,
    )
    verdict = evaluate_mission_assurance(
        rows,
        maximum_hard_failure_rate_upper_95=0.02,
        independent=True,
        real_domain=True,
        operational_environment=True,
    )
    assert not verdict.admissible
    assert verdict.hard_failure_count == 1


def test_local_or_synthetic_evidence_cannot_self_authorize():
    verdict = evaluate_mission_assurance(
        _rows(500), independent=False, real_domain=False, operational_environment=False
    )
    assert not verdict.admissible
    assert {
        "evaluation is not independent",
        "evaluation is not real-domain",
        "evaluation is not operationally representative",
    }.issubset(verdict.reasons)


def test_sufficient_zero_failure_evidence_can_pass_statistical_gate():
    verdict = evaluate_mission_assurance(
        _rows(500), independent=True, real_domain=True, operational_environment=True
    )
    assert verdict.admissible
    assert verdict.hard_failure_interval.upper < 0.01
    assert verdict.atomic_claim_interval is not None
    assert verdict.p99_latency_ms >= verdict.p95_latency_ms >= verdict.p50_latency_ms


def test_confidence_bound_alone_blocks_small_zero_failure_sample():
    verdict = evaluate_mission_assurance(
        _rows(30),
        minimum_cases=30,
        maximum_hard_failure_rate_upper_95=0.01,
        independent=True,
        real_domain=True,
        operational_environment=True,
    )
    assert not verdict.admissible
    assert any("upper 95% bound" in reason for reason in verdict.reasons)


def test_independence_alone_is_required_for_admission():
    verdict = evaluate_mission_assurance(
        _rows(500), independent=False, real_domain=True, operational_environment=True
    )
    assert not verdict.admissible
    assert verdict.reasons == ("evaluation is not independent",)


def test_an_observation_without_a_case_id_is_refused() -> None:
    """The id is how a verdict is traced back to the run that produced it.

    An interval computed over rows that cannot be named is a number nobody can audit,
    and the campaign's whole claim is that every figure in it has a case behind it.
    """
    with pytest.raises(ValueError, match="case_id is required"):
        MissionObservation(case_id="")


@pytest.mark.parametrize(
    ("atomic", "correct"),
    [(-1, 0), (0, 1), (2, 3), (5, -1), (-3, -3)],
)
def test_claim_counts_that_contradict_each_other_are_refused(atomic: int, correct: int) -> None:
    """Correct claims are a subset of claims made; the ratio is a proportion or nothing.

    `correct > atomic` produces a Wilson interval above 1.0 — a correctness rate over one
    hundred per cent, which would read as an unusually good system rather than as a
    corrupt row.
    """
    with pytest.raises(ValueError, match="atomic claim counts are inconsistent"):
        MissionObservation(case_id="c1", atomic_claims=atomic, correct_atomic_claims=correct)


@pytest.mark.parametrize("latency", [float("nan"), float("inf"), -float("inf"), -0.5])
def test_a_latency_that_is_not_a_finite_non_negative_number_is_refused(latency: float) -> None:
    """A NaN in the list makes the sorted order — and therefore every quantile — arbitrary."""
    with pytest.raises(ValueError, match="latency_ms must be finite"):
        MissionObservation(case_id="c1", latency_ms=latency)


def test_a_campaign_with_no_observations_reports_the_widest_interval_not_zero_risk() -> None:
    """No evidence is the widest possible interval, and latency quantiles are zero.

    Reporting a point estimate of zero failures from zero cases would be the strongest
    possible claim made from nothing.
    """
    verdict = evaluate_mission_assurance(
        [], independent=True, real_domain=True, operational_environment=True
    )
    assert verdict.observations == 0
    assert verdict.admissible is False
    assert (verdict.hard_failure_interval.lower, verdict.hard_failure_interval.upper) == (0.0, 1.0)
    assert verdict.atomic_claim_interval is None
    assert verdict.p50_latency_ms == 0.0
    assert verdict.p95_latency_ms == 0.0
    assert verdict.p99_latency_ms == 0.0


@pytest.mark.parametrize("minimum_cases", [0, -1, -400])
def test_a_non_positive_case_minimum_is_refused(minimum_cases: int) -> None:
    """A campaign that requires zero cases admits on no evidence at all."""
    with pytest.raises(ValueError, match="minimum_cases must be positive"):
        evaluate_mission_assurance(
            _rows(10),
            minimum_cases=minimum_cases,
            independent=True,
            real_domain=True,
            operational_environment=True,
        )


@pytest.mark.parametrize("bound", [0.0, 1.0, -0.1, 1.5, 2.0])
def test_a_hard_failure_bound_outside_the_open_unit_interval_is_refused(bound: float) -> None:
    """Zero is unattainable for any finite sample; one admits everything.

    Both ends turn the gate into a formality — the first can never pass, the second can
    never fail — and neither states a risk anybody chose.
    """
    with pytest.raises(ValueError, match="hard-failure bound must be in"):
        evaluate_mission_assurance(
            _rows(10),
            maximum_hard_failure_rate_upper_95=bound,
            independent=True,
            real_domain=True,
            operational_environment=True,
        )
