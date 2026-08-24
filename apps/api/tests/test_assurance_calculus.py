from __future__ import annotations

import itertools

import pytest

from korpus.application.assurance_calculus import (
    DimensionObservation,
    DimensionPolicy,
    EvidenceClass,
    EvidencePoint,
    GateRequirement,
    ReadinessPolicy,
    critical_path_blockers,
    dominates,
    evaluate_readiness,
    join_evidence,
    maximum_single_dimension_effect,
    weighted_score_is_bounded,
)

SOURCE = "a" * 64
OTHER_SOURCE = "b" * 64
RELEASE = "v0.4.0"


def evidence(
    status: str = "PASS",
    *,
    cls: EvidenceClass = EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL,
    source: str = SOURCE,
    release: str = RELEASE,
    independent: bool = False,
    attested: bool = False,
) -> EvidencePoint:
    return EvidencePoint(
        cls,
        source,
        release,
        status,
        executed=cls >= EvidenceClass.EXECUTED,
        negative_control=cls >= EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL,
        independent=independent,
        attested=attested,
    )


def policy() -> ReadinessPolicy:
    return ReadinessPolicy(
        dimensions=(
            DimensionPolicy("product", 0.20),
            DimensionPolicy("security", 0.25),
            DimensionPolicy("tevv", 0.25),
            DimensionPolicy("release", 0.20),
            DimensionPolicy("operations", 0.10),
        ),
        mandatory_gates=(
            GateRequirement("engineering", EvidenceClass.EXECUTED),
            GateRequirement(
                "redteam",
                EvidenceClass.INDEPENDENT_ATTESTED,
                require_negative_control=True,
                require_independent=True,
                require_attestation=True,
            ),
        ),
    )


def observations(score: float = 95.0) -> dict[str, DimensionObservation]:
    ev = evidence()
    return {
        item.dimension_id: DimensionObservation(score, ev)
        for item in policy().dimensions
    }


def test_policy_refuses_weights_that_do_not_sum_to_one() -> None:
    with pytest.raises(ValueError, match="weights must sum"):
        ReadinessPolicy(
            dimensions=(DimensionPolicy("a", 0.4), DimensionPolicy("b", 0.5)),
            mandatory_gates=(),
        )


def test_evidence_class_cannot_claim_execution_without_execution() -> None:
    with pytest.raises(ValueError, match="executed=True"):
        EvidencePoint(EvidenceClass.EXECUTED, SOURCE, RELEASE, "PASS")


def test_evidence_join_refuses_cross_source_aggregation() -> None:
    with pytest.raises(ValueError, match="different source/release"):
        join_evidence(evidence(), evidence(source=OTHER_SOURCE))


def test_conflicting_evidence_join_fails_closed() -> None:
    joined = join_evidence(evidence("PASS"), evidence("FAIL"))
    assert joined.status == "FAIL"
    assert not joined.passed


def test_stronger_same_identity_evidence_dominates_weaker() -> None:
    weak = evidence(cls=EvidenceClass.EXECUTED)
    strong = evidence(cls=EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL)
    assert dominates(strong, weak)
    assert not dominates(weak, strong)
    assert not dominates(strong, evidence(cls=EvidenceClass.EXECUTED, source=OTHER_SOURCE))


def test_unexecuted_evidence_caps_dimension_even_when_claimed_score_is_100() -> None:
    p = policy()
    declared = EvidencePoint(EvidenceClass.DECLARATIVE, SOURCE, RELEASE, "PASS")
    observed = observations()
    observed["product"] = DimensionObservation(100.0, declared)
    result = evaluate_readiness(
        p,
        observed,
        {
            "engineering": evidence(cls=EvidenceClass.EXECUTED),
            "redteam": evidence(
                cls=EvidenceClass.INDEPENDENT_ATTESTED,
                independent=True,
                attested=True,
            ),
        },
        source_digest=SOURCE,
        release=RELEASE,
    )
    assert result.dimension_scores["product"] == 70.0


def test_stale_dimension_evidence_contributes_zero() -> None:
    observed = observations()
    observed["security"] = DimensionObservation(99, evidence(source=OTHER_SOURCE))
    result = evaluate_readiness(
        policy(),
        observed,
        {},
        source_digest=SOURCE,
        release=RELEASE,
    )
    assert result.dimension_scores["security"] == 0.0


def test_high_weighted_score_cannot_compensate_for_missing_mandatory_gate() -> None:
    result = evaluate_readiness(
        policy(),
        observations(100.0),
        {"engineering": evidence(cls=EvidenceClass.EXECUTED)},
        source_digest=SOURCE,
        release=RELEASE,
    )
    assert result.engineering_readiness >= 90.0
    assert not result.production_authorized
    assert "redteam" in critical_path_blockers(
        policy(),
        {"engineering": evidence(cls=EvidenceClass.EXECUTED)},
        source_digest=SOURCE,
        release=RELEASE,
    )


def test_independent_attested_redteam_can_close_its_gate() -> None:
    gates = {
        "engineering": evidence(cls=EvidenceClass.EXECUTED),
        "redteam": evidence(
            cls=EvidenceClass.INDEPENDENT_ATTESTED,
            independent=True,
            attested=True,
        ),
    }
    result = evaluate_readiness(
        policy(), observations(), gates, source_digest=SOURCE, release=RELEASE
    )
    assert result.production_authorized
    assert result.blockers == ()


def test_release_binding_is_required_even_for_independent_attestation() -> None:
    gates = {
        "engineering": evidence(cls=EvidenceClass.EXECUTED),
        "redteam": evidence(
            cls=EvidenceClass.INDEPENDENT_ATTESTED,
            release="v9.9.9",
            independent=True,
            attested=True,
        ),
    }
    result = evaluate_readiness(
        policy(), observations(), gates, source_digest=SOURCE, release=RELEASE
    )
    assert not result.production_authorized
    assert "redteam.release_bound" in result.blockers


def test_maximum_single_dimension_effect_is_exactly_weight_times_100() -> None:
    effects = maximum_single_dimension_effect(policy())
    assert effects == {
        "product": 20.0,
        "security": 25.0,
        "tevv": 25.0,
        "release": 20.0,
        "operations": 10.0,
    }


def test_weighted_score_is_bounded_for_every_corner_of_the_hypercube() -> None:
    p = policy()
    for scores in itertools.product((0.0, 100.0), repeat=len(p.dimensions)):
        assert weighted_score_is_bounded(p, scores)


def test_weighted_score_refuses_wrong_arity_and_out_of_range_values() -> None:
    p = policy()
    assert not weighted_score_is_bounded(p, [100.0])
    assert not weighted_score_is_bounded(p, [0, 0, 0, 0, 101])


def test_unknown_outcome_is_information_bottom_not_a_conflict() -> None:
    passed = evidence("PASS")
    unknown = evidence("UNKNOWN")
    assert join_evidence(passed, unknown).status == "PASS"
    assert join_evidence(unknown, passed).status == "PASS"
    assert dominates(passed, unknown)


def test_pass_and_fail_are_incomparable_under_dominance() -> None:
    passed = evidence("PASS")
    failed = evidence("FAIL")
    assert not dominates(passed, failed)
    assert not dominates(failed, passed)
