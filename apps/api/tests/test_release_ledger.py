from __future__ import annotations

from datetime import UTC, datetime, timedelta

from korpus.application.assurance_calculus import EvidenceClass, EvidencePoint, GateRequirement
from korpus.application.release_ledger import (
    ReleaseLedgerEvent,
    append_promotion_event,
    append_withdrawal_event,
    verify_ledger,
)
from korpus.application.release_state_machine import (
    PromotionPolicy,
    ReleaseIdentity,
    ReleaseRecord,
    ReleaseStage,
)

SOURCE = "a" * 64
RELEASE = "v0.4.0"


def point(gate_id: str, cls: EvidenceClass) -> tuple[str, EvidencePoint]:
    independent = cls >= EvidenceClass.INDEPENDENT_ATTESTED
    return gate_id, EvidencePoint(
        cls,
        SOURCE,
        RELEASE,
        "PASS",
        executed=cls >= EvidenceClass.EXECUTED,
        negative_control=cls >= EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL,
        independent=independent,
        attested=independent,
    )


def policy() -> PromotionPolicy:
    unit = GateRequirement("unit", EvidenceClass.EXECUTED)
    mutation = GateRequirement("mutation", EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL, True)
    external = GateRequirement("external", EvidenceClass.INDEPENDENT_ATTESTED, True, True, True)
    return PromotionPolicy((unit,), (unit, mutation), (unit, mutation, external))


def test_release_ledger_hash_chain_survives_full_promotion_and_withdrawal() -> None:
    identity = ReleaseIdentity(RELEASE, SOURCE, "e" * 64)
    record = ReleaseRecord(identity, ReleaseStage.DRAFT, "author")
    events: list[ReleaseLedgerEvent] = []
    gates = dict(
        [
            point("unit", EvidenceClass.EXECUTED),
            point("mutation", EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL),
            point("external", EvidenceClass.INDEPENDENT_ATTESTED),
        ]
    )
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    for offset, target in enumerate(
        (
            ReleaseStage.INTEGRATED,
            ReleaseStage.VERIFIED,
            ReleaseStage.RELEASE_CANDIDATE,
            ReleaseStage.PRODUCTION_AUTHORIZED,
        )
    ):
        record, event = append_promotion_event(
            events,
            record,
            target,
            policy(),
            gates,
            verifier_subject="verifier" if target >= ReleaseStage.VERIFIED else None,
            timestamp=now + timedelta(minutes=offset),
        )
        events.append(event)
    record, withdrawn = append_withdrawal_event(
        events,
        record,
        "post-release evidence invalidated",
        timestamp=now + timedelta(minutes=5),
    )
    events.append(withdrawn)
    verdict = verify_ledger(
        events,
        expected_release_identity_digest=identity.canonical_digest,
        expected_head_sha256=events[-1].event_sha256,
    )
    assert verdict.valid, verdict.failures
    assert verdict.events == 5
    assert record.stage == ReleaseStage.WITHDRAWN


def test_ledger_detects_tampering_without_rehashing() -> None:
    identity = ReleaseIdentity(RELEASE, SOURCE, "e" * 64)
    record = ReleaseRecord(identity, ReleaseStage.DRAFT, "author")
    record, event = append_promotion_event(
        [],
        record,
        ReleaseStage.INTEGRATED,
        policy(),
        {},
        timestamp=datetime(2026, 8, 15, tzinfo=UTC),
    )
    tampered = ReleaseLedgerEvent(
        sequence=event.sequence,
        release_identity_digest=event.release_identity_digest,
        release=event.release,
        from_stage=event.from_stage,
        to_stage=event.to_stage,
        author_subject="attacker",
        verifier_subject=event.verifier_subject,
        gate_set_sha256=event.gate_set_sha256,
        timestamp=event.timestamp,
        previous_event_sha256=event.previous_event_sha256,
        withdrawal_reason=event.withdrawal_reason,
        event_sha256=event.event_sha256,
    )
    verdict = verify_ledger([tampered])
    assert not verdict.valid
    assert "event[1].hash" in verdict.failures


def test_ledger_detects_head_anchor_mismatch() -> None:
    identity = ReleaseIdentity(RELEASE, SOURCE, "e" * 64)
    record = ReleaseRecord(identity, ReleaseStage.DRAFT, "author")
    _, event = append_promotion_event(
        [],
        record,
        ReleaseStage.INTEGRATED,
        policy(),
        {},
        timestamp=datetime(2026, 8, 15, tzinfo=UTC),
    )
    verdict = verify_ledger([event], expected_head_sha256="f" * 64)
    assert not verdict.valid
    assert "ledger.head_anchor_mismatch" in verdict.failures


def test_ledger_detects_rehashed_broken_chain_link() -> None:
    identity = ReleaseIdentity(RELEASE, SOURCE, "e" * 64)
    gates = dict(
        [
            point("unit", EvidenceClass.EXECUTED),
            point("mutation", EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL),
        ]
    )
    record = ReleaseRecord(identity, ReleaseStage.DRAFT, "author")
    record, first = append_promotion_event(
        [],
        record,
        ReleaseStage.INTEGRATED,
        policy(),
        gates,
        timestamp=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )
    record, second = append_promotion_event(
        [first],
        record,
        ReleaseStage.VERIFIED,
        policy(),
        gates,
        verifier_subject="verifier",
        timestamp=datetime(2026, 8, 15, 12, 1, tzinfo=UTC),
    )
    # An attacker who can rewrite the local file can recompute the second event hash.
    # The previous-event commitment must still expose that the chain was severed.
    severed = ReleaseLedgerEvent(
        **{
            **second.unsigned_record(),
            "previous_event_sha256": "f" * 64,
        }
    ).with_hash()
    verdict = verify_ledger([first, severed])
    assert not verdict.valid
    assert "event[2].previous_hash" in verdict.failures
