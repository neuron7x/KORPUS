from korpus.application.evaluation_validity import (
    AdmissionPolicy,
    CampaignContext,
    EvaluationObservation,
    HardFailureClass,
    TEVVDimension,
    evaluate_campaign,
    wilson_interval,
)
from korpus.application.evaluation_validity import (
    TestedSystemIdentity as SystemIdentity,
)

HEX = "a" * 64


def identity() -> SystemIdentity:
    return SystemIdentity(
        source_tree_sha256=HEX,
        release="v-test",
        harness_sha256="b" * 64,
        dataset_sha256="c" * 64,
        configuration_sha256="d" * 64,
        environment_identity="postgres-17/python-3.12.13/container-sha256:x",
    )


def obs(i: int, *, failure: HardFailureClass | None = None) -> EvaluationObservation:
    return EvaluationObservation(
        id=f"case-{i}",
        cohort="operator",
        dimensions=frozenset(TEVVDimension),
        passed=failure is None,
        hard_failures=(() if failure is None else (failure,)),
        latency_ms=float(i % 10),
    )


def ctx(**changes) -> CampaignContext:
    values = dict(
        tested_system=identity(),
        independent_evaluation=True,
        real_domain=True,
        operational_environment=True,
    )
    values.update(changes)
    return CampaignContext(**values)


def policy(**changes) -> AdmissionPolicy:
    values = dict(
        minimum_cases=400,
        minimum_cases_per_required_cohort=30,
        required_cohorts=frozenset({"operator"}),
    )
    values.update(changes)
    return AdmissionPolicy(**values)


def test_zero_failures_400_cases_satisfies_one_percent_wilson_upper_bound():
    result = evaluate_campaign([obs(i) for i in range(400)], context=ctx(), policy=policy())
    assert result["metrics"]["hard_failure_rate_upper_95"] < 0.01
    assert result["admitted"] is True


def test_100_percent_accuracy_is_not_enough_without_independence():
    result = evaluate_campaign(
        [obs(i) for i in range(400)], context=ctx(independent_evaluation=False), policy=policy()
    )
    assert result["checks"]["independent_evaluation"] is False
    assert result["admitted"] is False


def test_100_percent_accuracy_is_not_enough_on_synthetic_domain():
    result = evaluate_campaign(
        [obs(i) for i in range(400)], context=ctx(real_domain=False), policy=policy()
    )
    assert result["checks"]["real_domain"] is False
    assert result["admitted"] is False


def test_single_hard_failure_is_conjunctive_release_failure():
    rows = [obs(i) for i in range(399)] + [obs(399, failure=HardFailureClass.ACCESS_LEAKAGE)]
    result = evaluate_campaign(rows, context=ctx(), policy=policy())
    assert result["metrics"]["pass_rate"] == 399 / 400
    assert result["checks"]["hard_failure_count_within_limit"] is False
    assert result["admitted"] is False


def test_rare_event_uncertainty_blocks_tiny_zero_failure_campaign():
    result = evaluate_campaign(
        [obs(i) for i in range(50)],
        context=ctx(),
        policy=policy(minimum_cases=1),
    )
    assert result["metrics"]["hard_failure_rate_upper_95"] > 0.01
    assert result["admitted"] is False


def test_missing_required_cohort_cannot_be_hidden_by_aggregate_volume():
    result = evaluate_campaign(
        [obs(i) for i in range(400)],
        context=ctx(),
        policy=policy(required_cohorts=frozenset({"operator", "instructor"})),
    )
    assert result["cohort_checks"]["instructor"] is False
    assert result["admitted"] is False


def test_duplicate_case_ids_fail_closed():
    rows = [obs(i) for i in range(399)] + [obs(1)]
    result = evaluate_campaign(rows, context=ctx(), policy=policy())
    assert result["checks"]["observation_ids_unique"] is False
    assert result["admitted"] is False


def test_system_identity_fingerprint_changes_with_harness():
    a = identity()
    b = a.model_copy(update={"harness_sha256": "e" * 64})
    assert a.fingerprint != b.fingerprint


def test_wilson_interval_has_expected_zero_failure_upper_bound():
    low, high = wilson_interval(0, 400)
    assert low == 0.0
    assert 0.009 < high < 0.01
