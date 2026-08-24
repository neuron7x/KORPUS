from __future__ import annotations

import pytest

from korpus.application.assurance_calculus import EvidenceClass, EvidencePoint, GateRequirement
from korpus.application.release_state_machine import (
    PromotionPolicy,
    ReleaseIdentity,
    ReleaseRecord,
    ReleaseStage,
    evaluate_promotion,
    promote,
    withdraw,
)

SOURCE = "a" * 64
EVIDENCE = "e" * 64
RELEASE = "v0.4.0"


def gate(
    gate_id: str,
    *,
    source: str = SOURCE,
    release: str = RELEASE,
    independent: bool = False,
) -> tuple[str, EvidencePoint]:
    cls = EvidenceClass.INDEPENDENT_ATTESTED if independent else EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL
    return gate_id, EvidencePoint(
        cls,
        source,
        release,
        "PASS",
        executed=True,
        negative_control=True,
        independent=independent,
        attested=independent,
    )


def policy() -> PromotionPolicy:
    unit = GateRequirement("unit", EvidenceClass.EXECUTED)
    mutation = GateRequirement("mutation", EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL, True)
    external = GateRequirement(
        "external_redteam",
        EvidenceClass.INDEPENDENT_ATTESTED,
        True,
        True,
        True,
    )
    return PromotionPolicy(
        verification_gates=(unit,),
        candidate_gates=(unit, mutation),
        production_gates=(unit, mutation, external),
    )


def record(stage: ReleaseStage = ReleaseStage.DRAFT) -> ReleaseRecord:
    return ReleaseRecord(
        ReleaseIdentity(RELEASE, SOURCE, EVIDENCE),
        stage,
        author_subject="author-1",
    )


def test_release_identity_digest_is_deterministic_and_domain_separated() -> None:
    first = record().identity.canonical_digest
    second = ReleaseIdentity(RELEASE, SOURCE, EVIDENCE).canonical_digest
    assert first == second
    assert len(first) == 64
    assert first not in {SOURCE, EVIDENCE}


def test_release_identity_rejects_non_sha_digests() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        ReleaseIdentity(RELEASE, "abc", EVIDENCE)


def test_promotion_must_be_sequential() -> None:
    verdict = evaluate_promotion(record(), ReleaseStage.VERIFIED, policy(), {})
    assert not verdict.allowed
    assert verdict.failures == ("release.non_sequential_transition",)


def test_draft_to_integrated_does_not_require_assurance_gate_yet() -> None:
    result = promote(record(), ReleaseStage.INTEGRATED, policy(), {})
    assert result.stage == ReleaseStage.INTEGRATED
    assert result.identity == record().identity


def test_verified_requires_verifier_and_exact_source_bound_gate() -> None:
    integrated = record(ReleaseStage.INTEGRATED)
    gates = dict([gate("unit")])
    missing = evaluate_promotion(integrated, ReleaseStage.VERIFIED, policy(), gates)
    assert "release.verifier_missing" in missing.failures
    stale = dict([gate("unit", source="b" * 64)])
    wrong = evaluate_promotion(
        integrated,
        ReleaseStage.VERIFIED,
        policy(),
        stale,
        verifier_subject="verifier-1",
    )
    assert "unit.source_bound" in wrong.failures


def test_candidate_requires_mutation_negative_control() -> None:
    verified = record(ReleaseStage.VERIFIED)
    weak_mutation = EvidencePoint(
        EvidenceClass.EXECUTED,
        SOURCE,
        RELEASE,
        "PASS",
        executed=True,
    )
    verdict = evaluate_promotion(
        verified,
        ReleaseStage.RELEASE_CANDIDATE,
        policy(),
        {"unit": gate("unit")[1], "mutation": weak_mutation},
        verifier_subject="verifier-1",
    )
    assert not verdict.allowed
    assert "mutation.evidence_class" in verdict.failures
    assert "mutation.negative_control" in verdict.failures


def test_production_authorization_requires_independent_verifier() -> None:
    candidate = record(ReleaseStage.RELEASE_CANDIDATE)
    gates = dict([gate("unit"), gate("mutation"), gate("external_redteam", independent=True)])
    verdict = evaluate_promotion(
        candidate,
        ReleaseStage.PRODUCTION_AUTHORIZED,
        policy(),
        gates,
        verifier_subject="author-1",
    )
    assert not verdict.allowed
    assert "release.verifier_not_independent" in verdict.failures


def test_full_gate_set_and_independent_verifier_authorize_production() -> None:
    candidate = record(ReleaseStage.RELEASE_CANDIDATE)
    gates = dict([gate("unit"), gate("mutation"), gate("external_redteam", independent=True)])
    production = promote(
        candidate,
        ReleaseStage.PRODUCTION_AUTHORIZED,
        policy(),
        gates,
        verifier_subject="verifier-2",
    )
    assert production.stage == ReleaseStage.PRODUCTION_AUTHORIZED
    assert production.verifier_subject == "verifier-2"
    assert production.identity == candidate.identity


def test_authorized_release_cannot_move_back_to_candidate() -> None:
    production = record(ReleaseStage.PRODUCTION_AUTHORIZED)
    verdict = evaluate_promotion(
        production,
        ReleaseStage.RELEASE_CANDIDATE,
        policy(),
        {},
        verifier_subject="verifier-2",
    )
    assert not verdict.allowed


def test_withdrawal_is_the_only_general_safety_escape() -> None:
    production = record(ReleaseStage.PRODUCTION_AUTHORIZED)
    withdrawn = withdraw(production, "critical post-release evidence invalidated")
    assert withdrawn.stage == ReleaseStage.WITHDRAWN
    assert withdrawn.withdrawal_reason == "critical post-release evidence invalidated"
    with pytest.raises(ValueError, match="already withdrawn"):
        withdraw(withdrawn, "again")


def test_withdrawal_cannot_be_smuggled_through_generic_promotion_api() -> None:
    production = record(ReleaseStage.PRODUCTION_AUTHORIZED)
    verdict = evaluate_promotion(
        production,
        ReleaseStage.WITHDRAWN,
        policy(),
        {},
        verifier_subject="verifier-2",
    )
    assert not verdict.allowed
    assert verdict.failures == ("release.withdrawal_requires_reason",)
    with pytest.raises(ValueError, match="withdrawal_requires_reason"):
        promote(
            production,
            ReleaseStage.WITHDRAWN,
            policy(),
            {},
            verifier_subject="verifier-2",
        )
