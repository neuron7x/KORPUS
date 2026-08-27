"""Tamper-evident release-promotion ledger.

`release_state_machine` decides whether a transition is admissible. This module records
what actually happened as an append-only hash chain so a release candidate is not just a
mutable JSON field saying "authorized". The chain is deliberately simple and portable:
each event commits the previous event hash, the immutable release identity, the exact
from/to stages, actors, gate-set digest and an RFC 3339 UTC timestamp.

A local hash chain detects edits, reordering and interior deletion. It cannot by itself
detect deletion of the final suffix; production therefore has to anchor the head outside
the build environment (for example an independently controlled transparency log or CI
attestation). That external anchor is represented explicitly rather than implied.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from korpus.application.assurance_calculus import EvidencePoint
from korpus.application.release_state_machine import (
    PromotionPolicy,
    ReleaseRecord,
    ReleaseStage,
    promote,
    withdraw,
)

_LEDGER_DOMAIN = b"korpus-release-ledger-v1\0"
_GENESIS = "0" * 64


def _sha256_hex(value: str, label: str) -> str:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{label} must be SHA-256 hex")
    return value


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("timestamp must be RFC 3339 / ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must carry a timezone")
    return parsed.astimezone(UTC)


def gate_set_digest(gates: Mapping[str, EvidencePoint]) -> str:
    """Commit the exact gate evidence used to justify a transition."""
    records = []
    for gate_id, point in sorted(gates.items()):
        records.append(
            {
                "gate_id": gate_id,
                "evidence_class": int(point.evidence_class),
                "source_digest": point.source_digest,
                "release": point.release,
                "status": point.status,
                "executed": point.executed,
                "negative_control": point.negative_control,
                "independent": point.independent,
                "attested": point.attested,
            }
        )
    payload = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b"korpus-gate-set-v1\0" + payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ReleaseLedgerEvent:
    sequence: int
    release_identity_digest: str
    release: str
    from_stage: str
    to_stage: str
    author_subject: str
    verifier_subject: str | None
    gate_set_sha256: str
    timestamp: str
    previous_event_sha256: str
    withdrawal_reason: str | None = None
    event_sha256: str = ""

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("ledger sequence starts at 1")
        _sha256_hex(self.release_identity_digest, "release_identity_digest")
        _sha256_hex(self.gate_set_sha256, "gate_set_sha256")
        _sha256_hex(self.previous_event_sha256, "previous_event_sha256")
        if self.event_sha256:
            _sha256_hex(self.event_sha256, "event_sha256")
        if not self.release.startswith("v"):
            raise ValueError("release must be a version tag")
        if not self.author_subject.strip():
            raise ValueError("author_subject is required")
        _timestamp(self.timestamp)
        ReleaseStage[self.from_stage]
        ReleaseStage[self.to_stage]
        if (
            self.to_stage == ReleaseStage.WITHDRAWN.name
            and not (self.withdrawal_reason or "").strip()
        ):
            raise ValueError("withdrawal ledger event requires a reason")

    def unsigned_record(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "release_identity_digest": self.release_identity_digest,
            "release": self.release,
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "author_subject": self.author_subject,
            "verifier_subject": self.verifier_subject,
            "gate_set_sha256": self.gate_set_sha256,
            "timestamp": self.timestamp,
            "previous_event_sha256": self.previous_event_sha256,
            "withdrawal_reason": self.withdrawal_reason,
        }

    @property
    def computed_sha256(self) -> str:
        payload = json.dumps(self.unsigned_record(), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(_LEDGER_DOMAIN + payload).hexdigest()

    def with_hash(self) -> ReleaseLedgerEvent:
        return replace(self, event_sha256=self.computed_sha256)

    def as_dict(self) -> dict[str, object]:
        return {**self.unsigned_record(), "event_sha256": self.event_sha256 or self.computed_sha256}


@dataclass(frozen=True, slots=True)
class LedgerVerification:
    valid: bool
    head_sha256: str
    events: int
    failures: tuple[str, ...]


def append_promotion_event(
    events: Iterable[ReleaseLedgerEvent],
    record: ReleaseRecord,
    target: ReleaseStage,
    policy: PromotionPolicy,
    gates: Mapping[str, EvidencePoint],
    *,
    verifier_subject: str | None = None,
    timestamp: datetime | None = None,
) -> tuple[ReleaseRecord, ReleaseLedgerEvent]:
    """Promote and emit one ledger event in one logical operation."""
    existing = tuple(events)
    prior = existing[-1].event_sha256 if existing else _GENESIS
    if existing and not prior:
        prior = existing[-1].computed_sha256
    next_record = promote(
        record,
        target,
        policy,
        gates,
        verifier_subject=verifier_subject,
    )
    instant = (timestamp or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    event = ReleaseLedgerEvent(
        sequence=len(existing) + 1,
        release_identity_digest=record.identity.canonical_digest,
        release=record.identity.release,
        from_stage=record.stage.name,
        to_stage=target.name,
        author_subject=record.author_subject,
        verifier_subject=verifier_subject,
        gate_set_sha256=gate_set_digest(gates),
        timestamp=instant,
        previous_event_sha256=prior,
    ).with_hash()
    return next_record, event


def append_withdrawal_event(
    events: Iterable[ReleaseLedgerEvent],
    record: ReleaseRecord,
    reason: str,
    *,
    timestamp: datetime | None = None,
) -> tuple[ReleaseRecord, ReleaseLedgerEvent]:
    existing = tuple(events)
    prior = existing[-1].event_sha256 if existing else _GENESIS
    if existing and not prior:
        prior = existing[-1].computed_sha256
    next_record = withdraw(record, reason)
    instant = (timestamp or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    event = ReleaseLedgerEvent(
        sequence=len(existing) + 1,
        release_identity_digest=record.identity.canonical_digest,
        release=record.identity.release,
        from_stage=record.stage.name,
        to_stage=ReleaseStage.WITHDRAWN.name,
        author_subject=record.author_subject,
        verifier_subject=record.verifier_subject,
        gate_set_sha256=hashlib.sha256(b"korpus-withdrawal-no-gates-v1\0").hexdigest(),
        timestamp=instant,
        previous_event_sha256=prior,
        withdrawal_reason=next_record.withdrawal_reason,
    ).with_hash()
    return next_record, event


def _event_integrity_failures(
    index: int,
    event: ReleaseLedgerEvent,
    *,
    previous_hash: str,
    previous_to: str | None,
    previous_time: datetime | None,
) -> tuple[list[str], datetime]:
    failures: list[str] = []
    if event.sequence != index:
        failures.append(f"event[{index}].sequence")
    if event.previous_event_sha256 != previous_hash:
        failures.append(f"event[{index}].previous_hash")
    if event.event_sha256 != event.computed_sha256:
        failures.append(f"event[{index}].hash")
    if previous_to is not None and event.from_stage != previous_to:
        failures.append(f"event[{index}].stage_continuity")
    current_time = _timestamp(event.timestamp)
    if previous_time is not None and current_time < previous_time:
        failures.append(f"event[{index}].timestamp_monotonicity")

    from_stage = ReleaseStage[event.from_stage]
    to_stage = ReleaseStage[event.to_stage]
    if to_stage == ReleaseStage.WITHDRAWN and not (event.withdrawal_reason or "").strip():
        failures.append(f"event[{index}].withdrawal_reason")
    if to_stage != ReleaseStage.WITHDRAWN and int(to_stage) != int(from_stage) + 1:
        failures.append(f"event[{index}].non_sequential_transition")
    if from_stage == ReleaseStage.WITHDRAWN:
        failures.append(f"event[{index}].transition_after_withdrawal")
    return failures, current_time


def _identity_failures(
    index: int,
    event: ReleaseLedgerEvent,
    *,
    identity: str | None,
    release: str | None,
) -> list[str]:
    failures: list[str] = []
    if identity is not None and event.release_identity_digest != identity:
        failures.append(f"event[{index}].release_identity")
    if release is not None and event.release != release:
        failures.append(f"event[{index}].release")
    return failures


def verify_ledger(
    events: Iterable[ReleaseLedgerEvent],
    *,
    expected_release_identity_digest: str | None = None,
    expected_head_sha256: str | None = None,
) -> LedgerVerification:
    """Verify ordering, hash continuity, identity continuity and monotone transitions."""
    sequence = tuple(events)
    failures: list[str] = []
    previous_hash = _GENESIS
    previous_to: str | None = None
    previous_time: datetime | None = None
    identity: str | None = expected_release_identity_digest
    release: str | None = None

    for index, event in enumerate(sequence, 1):
        failures.extend(_identity_failures(index, event, identity=identity, release=release))
        event_failures, current_time = _event_integrity_failures(
            index,
            event,
            previous_hash=previous_hash,
            previous_to=previous_to,
            previous_time=previous_time,
        )
        failures.extend(event_failures)
        identity = identity or event.release_identity_digest
        release = release or event.release
        previous_hash = event.event_sha256
        previous_to = event.to_stage
        previous_time = current_time

    head = previous_hash
    if expected_head_sha256 is not None and head != expected_head_sha256:
        failures.append("ledger.head_anchor_mismatch")
    return LedgerVerification(not failures, head, len(sequence), tuple(failures))
