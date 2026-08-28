import pytest
from korpus.application.evaluation_validity import (
    AdmissionPolicy,
    CampaignContext,
    EvaluationObservation,
    HardFailureClass,
    TEVVDimension,
    evaluate_campaign,
    percentile,
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
        deployment_simulation=True,
        evaluation_cues_blinded=True,
        dependency_failures_simulated=True,
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


def test_static_eval_is_not_enough_without_deployment_simulation_controls():
    result = evaluate_campaign(
        [obs(i) for i in range(400)],
        context=ctx(
            deployment_simulation=False,
            evaluation_cues_blinded=False,
            dependency_failures_simulated=False,
        ),
        policy=policy(),
    )

    assert result["checks"]["deployment_simulation"] is False
    assert result["checks"]["evaluation_cues_blinded"] is False
    assert result["checks"]["dependency_failures_simulated"] is False
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


def test_an_observation_that_failed_hard_cannot_be_recorded_as_passed() -> None:
    """The two fields are not independent: one is a verdict, the other its evidence.

    A row carrying `citation_fabrication` and `passed=True` would count toward the pass
    rate and toward the hard-failure ledger at once, and the campaign's own consistency
    check compares those two numbers. Refusing the row at construction is what keeps the
    comparison meaningful.
    """
    for failure in HardFailureClass:
        with pytest.raises(ValueError, match="hard failure cannot be marked passed"):
            EvaluationObservation(
                id="case-1",
                cohort="operator",
                dimensions=frozenset(TEVVDimension),
                passed=True,
                hard_failures=(failure,),
                latency_ms=1.0,
            )


def test_an_observation_that_failed_hard_and_is_marked_failed_is_admitted() -> None:
    """The dual: refusing every combination would satisfy the assertion above."""
    observation = EvaluationObservation(
        id="case-1",
        cohort="operator",
        dimensions=frozenset(TEVVDimension),
        passed=False,
        hard_failures=(next(iter(HardFailureClass)),),
        latency_ms=1.0,
    )
    assert observation.hard_failures


@pytest.mark.parametrize("q", [-0.001, 1.001, float("nan"), float("inf"), -float("inf")])
def test_a_quantile_outside_the_unit_interval_is_refused(q: float) -> None:
    """A p150 latency is not a slow number; it is a question with no answer."""
    with pytest.raises(ValueError, match="q must be finite"):
        percentile([1.0, 2.0], q)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_a_non_finite_measurement_is_refused_before_it_is_sorted(bad: float) -> None:
    """NaN has no order, so a list containing one sorts differently on different runs.

    The percentile would then depend on where the NaN happened to land, and two runs of
    the same campaign would report two latencies from identical observations.
    """
    with pytest.raises(ValueError, match="percentile values must be finite"):
        percentile([1.0, bad, 3.0], 0.95)


def test_percentile_boundaries_are_defined_rather_than_interpolated_off_the_end() -> None:
    """Zero, one and two measurements are the cases a campaign actually starts with."""
    assert percentile([], 0.95) is None
    assert percentile([7.0], 0.95) == 7.0
    assert percentile([1.0, 3.0], 0.0) == 1.0
    assert percentile([1.0, 3.0], 1.0) == 3.0
    assert percentile([1.0, 3.0], 0.5) == 2.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert percentile([4.0, 1.0, 3.0, 2.0], 0.25) == 1.75
