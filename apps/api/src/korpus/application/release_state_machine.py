"""Release promotion as an explicit monotone state machine.

The state machine is intentionally stricter than a CI workflow.  CI can say that a
job is green; this module answers whether evidence for the exact source/release is
sufficient to change the semantic state of a release.  Production authorization is a
one-way transition: after authorization, the only safety transition is WITHDRAWN.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import IntEnum
from typing import Mapping

from korpus.application.assurance_calculus import EvidencePoint, GateRequirement, evaluate_gate


class ReleaseStage(IntEnum):
    DRAFT = 0
    INTEGRATED = 1
    VERIFIED = 2
    RELEASE_CANDIDATE = 3
    PRODUCTION_AUTHORIZED = 4
    WITHDRAWN = 5


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    release: str
    source_digest: str
    evidence_digest: str

    def __post_init__(self) -> None:
        for label, value in (
            ("source_digest", self.source_digest),
            ("evidence_digest", self.evidence_digest),
        ):
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError(f"{label} must be SHA-256 hex")
        if not self.release.startswith("v") or len(self.release) < 2:
            raise ValueError("release must be a version tag beginning with v")

    @property
    def canonical_digest(self) -> str:
        payload = json.dumps(
            {
                "release": self.release,
                "source_digest": self.source_digest,
                "evidence_digest": self.evidence_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(b"korpus-release-identity-v2\0" + payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ReleaseRecord:
    identity: ReleaseIdentity
    stage: ReleaseStage
    author_subject: str
    verifier_subject: str | None = None
    withdrawal_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.author_subject:
            raise ValueError("author_subject is required")
        if self.stage == ReleaseStage.WITHDRAWN and not self.withdrawal_reason:
            raise ValueError("withdrawn releases require a reason")


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    verification_gates: tuple[GateRequirement, ...]
    candidate_gates: tuple[GateRequirement, ...]
    production_gates: tuple[GateRequirement, ...]
    independent_verifier_required: bool = True


@dataclass(frozen=True, slots=True)
class PromotionVerdict:
    allowed: bool
    target: ReleaseStage
    failures: tuple[str, ...]


_ALLOWED_NEXT = {
    ReleaseStage.DRAFT: ReleaseStage.INTEGRATED,
    ReleaseStage.INTEGRATED: ReleaseStage.VERIFIED,
    ReleaseStage.VERIFIED: ReleaseStage.RELEASE_CANDIDATE,
    ReleaseStage.RELEASE_CANDIDATE: ReleaseStage.PRODUCTION_AUTHORIZED,
}


def _requirements(policy: PromotionPolicy, target: ReleaseStage) -> tuple[GateRequirement, ...]:
    if target == ReleaseStage.VERIFIED:
        return policy.verification_gates
    if target == ReleaseStage.RELEASE_CANDIDATE:
        return policy.candidate_gates
    if target == ReleaseStage.PRODUCTION_AUTHORIZED:
        return policy.production_gates
    return ()

def evaluate_promotion(
    record: ReleaseRecord,
    target: ReleaseStage,
    policy: PromotionPolicy,
    gates: Mapping[str, EvidencePoint],
    *,
    verifier_subject: str | None = None,
) -> PromotionVerdict:
    """Evaluate one transition without mutating release state."""

    if target == ReleaseStage.WITHDRAWN:
        # Withdrawal is reason-bearing and has a dedicated API.
        return PromotionVerdict(False, target, ("release.withdrawal_requires_reason",))
    expected = _ALLOWED_NEXT.get(record.stage)
    if expected != target:
        return PromotionVerdict(False, target, ("release.non_sequential_transition",))

    failures: list[str] = []
    for requirement in _requirements(policy, target):
        passed, reasons = evaluate_gate(
            requirement,
            gates.get(requirement.gate_id),
            source_digest=record.identity.source_digest,
            release=record.identity.release,
        )
        if not passed:
            failures.extend(reasons)

    if target >= ReleaseStage.VERIFIED and not verifier_subject:
        failures.append("release.verifier_missing")
    if (
        target == ReleaseStage.PRODUCTION_AUTHORIZED
        and policy.independent_verifier_required
        and verifier_subject == record.author_subject
    ):
        failures.append("release.verifier_not_independent")

    return PromotionVerdict(not failures, target, tuple(failures))


def promote(
    record: ReleaseRecord,
    target: ReleaseStage,
    policy: PromotionPolicy,
    gates: Mapping[str, EvidencePoint],
    *,
    verifier_subject: str | None = None,
) -> ReleaseRecord:
    verdict = evaluate_promotion(
        record,
        target,
        policy,
        gates,
        verifier_subject=verifier_subject,
    )
    if not verdict.allowed:
        raise ValueError("release promotion refused: " + ", ".join(verdict.failures))
    return ReleaseRecord(
        identity=record.identity,
        stage=target,
        author_subject=record.author_subject,
        verifier_subject=verifier_subject or record.verifier_subject,
    )


def withdraw(record: ReleaseRecord, reason: str) -> ReleaseRecord:
    if record.stage == ReleaseStage.WITHDRAWN:
        raise ValueError("release is already withdrawn")
    normalized = reason.strip()
    if not normalized:
        raise ValueError("withdrawal reason must be non-empty")
    return ReleaseRecord(
        identity=record.identity,
        stage=ReleaseStage.WITHDRAWN,
        author_subject=record.author_subject,
        verifier_subject=record.verifier_subject,
        withdrawal_reason=normalized,
    )
