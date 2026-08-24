from __future__ import annotations

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
