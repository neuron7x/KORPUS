"""Conflict-preserving evidence fusion for release assurance.

Only evidence for the same source/release identity and the same claim key can be
combined. Compatible observations are deduplicated while retaining the strongest
available evidence class. Contradictory observations are never averaged, voted away,
or silently collapsed: they remain explicit conflicts and the fused claim is FAIL.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from korpus.application.assurance_calculus import EvidenceClass, EvidencePoint, join_evidence


@dataclass(frozen=True, slots=True)
class ClaimEvidence:
    claim_id: str
    value: str
    source_id: str
    point: EvidencePoint

    def __post_init__(self) -> None:
        if not self.claim_id:
            raise ValueError("claim_id is required")
        if not self.source_id:
            raise ValueError("source_id is required")


@dataclass(frozen=True, slots=True)
class EvidenceConflict:
    claim_id: str
    left_source_id: str
    right_source_id: str
    left_value: str
    right_value: str
    reason: str


@dataclass(frozen=True, slots=True)
class FusedClaim:
    claim_id: str
    value: str | None
    point: EvidencePoint
    source_ids: tuple[str, ...]
    conflicts: tuple[EvidenceConflict, ...]

    @property
    def conflicted(self) -> bool:
        return bool(self.conflicts)


def _identity(point: EvidencePoint) -> tuple[str, str]:
    return point.source_digest, point.release


def _strongest(points: Iterable[EvidencePoint]) -> EvidencePoint:
    iterator = iter(points)
    try:
        current = next(iterator)
    except StopIteration as exc:
        raise ValueError("cannot fuse an empty evidence set") from exc
    for point in iterator:
        current = join_evidence(current, point)
    return current


def _validate_fusion_scope(observations: tuple[ClaimEvidence, ...]) -> tuple[str, str]:
    if not observations:
        raise ValueError("cannot fuse an empty evidence set")
    if len({item.claim_id for item in observations}) != 1:
        raise ValueError("all observations must refer to one claim_id")
    identities = {_identity(item.point) for item in observations}
    if len(identities) != 1:
        raise ValueError("cannot fuse evidence from different source/release identities")
    return next(iter(identities))


def _pair_conflict(left: ClaimEvidence, right: ClaimEvidence) -> EvidenceConflict | None:
    if left.value != right.value:
        reason = "value_conflict"
    elif {left.point.status, right.point.status} == {"PASS", "FAIL"}:
        reason = "outcome_conflict"
    else:
        return None
    return EvidenceConflict(
        claim_id=left.claim_id,
        left_source_id=left.source_id,
        right_source_id=right.source_id,
        left_value=left.value,
        right_value=right.value,
        reason=reason,
    )


def _conflicts(observations: tuple[ClaimEvidence, ...]) -> tuple[EvidenceConflict, ...]:
    found: list[EvidenceConflict] = []
    for index, left in enumerate(observations):
        for right in observations[index + 1 :]:
            conflict = _pair_conflict(left, right)
            if conflict is not None:
                found.append(conflict)
    return tuple(found)


def _failed_point(
    observations: tuple[ClaimEvidence, ...], identity: tuple[str, str]
) -> EvidencePoint:
    source_digest, release = identity
    strongest = max(item.point.evidence_class for item in observations)
    return EvidencePoint(
        EvidenceClass(strongest),
        source_digest,
        release,
        "FAIL",
        executed=any(item.point.executed for item in observations),
        negative_control=any(item.point.negative_control for item in observations),
        independent=any(item.point.independent for item in observations),
        attested=any(item.point.attested for item in observations),
    )


def fuse_claim_evidence(items: Iterable[ClaimEvidence]) -> FusedClaim:
    """Fuse compatible evidence and preserve every contradiction explicitly."""

    observations = tuple(items)
    identity = _validate_fusion_scope(observations)
    conflicts = _conflicts(observations)
    point = (
        _failed_point(observations, identity)
        if conflicts
        else _strongest(item.point for item in observations)
    )
    return FusedClaim(
        claim_id=observations[0].claim_id,
        value=None if conflicts else observations[0].value,
        point=point,
        source_ids=tuple(sorted({item.source_id for item in observations})),
        conflicts=conflicts,
    )
