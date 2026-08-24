from __future__ import annotations

import pytest

from korpus.application.assurance_calculus import EvidenceClass, EvidencePoint
from korpus.application.evidence_fusion import ClaimEvidence, fuse_claim_evidence

SOURCE = "a" * 64
RELEASE = "v0.8.0"


def point(status: str = "PASS", cls: EvidenceClass = EvidenceClass.EXECUTED) -> EvidencePoint:
    return EvidencePoint(cls, SOURCE, RELEASE, status, executed=cls >= EvidenceClass.EXECUTED)


def test_compatible_observations_merge_without_conflict() -> None:
    result = fuse_claim_evidence(
        [
            ClaimEvidence("claim", "same", "a", point()),
            ClaimEvidence("claim", "same", "b", point()),
        ]
    )
    assert result.value == "same"
    assert result.point.status == "PASS"
    assert result.source_ids == ("a", "b")
    assert result.conflicts == ()


def test_conflicting_values_remain_explicit_and_fail_closed() -> None:
    result = fuse_claim_evidence(
        [
            ClaimEvidence("claim", "left", "a", point()),
            ClaimEvidence("claim", "right", "b", point()),
        ]
    )
    assert result.value is None
    assert result.point.status == "FAIL"
    assert result.conflicted
    assert result.conflicts[0].reason == "value_conflict"


def test_conflicting_outcomes_remain_explicit() -> None:
    result = fuse_claim_evidence(
        [
            ClaimEvidence("claim", "same", "a", point("PASS")),
            ClaimEvidence("claim", "same", "b", point("FAIL")),
        ]
    )
    assert result.point.status == "FAIL"
    assert any(item.reason == "outcome_conflict" for item in result.conflicts)


def test_cross_identity_merge_is_rejected() -> None:
    foreign = EvidencePoint(EvidenceClass.EXECUTED, "b" * 64, RELEASE, "PASS", executed=True)
    with pytest.raises(ValueError, match="different source/release"):
        fuse_claim_evidence(
            [ClaimEvidence("claim", "same", "a", point()), ClaimEvidence("claim", "same", "b", foreign)]
        )


def test_cross_claim_merge_is_rejected() -> None:
    with pytest.raises(ValueError, match="one claim_id"):
        fuse_claim_evidence(
            [ClaimEvidence("a", "same", "a", point()), ClaimEvidence("b", "same", "b", point())]
        )
