from __future__ import annotations

import base64
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from korpus.application.release_state_machine import ReleaseIdentity, ReleaseRecord, ReleaseStage, withdraw
from korpus.application.resilience import AdmissionController, CircuitBreaker, CircuitOpenError
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentCreate,
    DocumentRecord,
    DocumentVersionRecord,
    ReviewState,
    VersionCreate,
)
from korpus.security.attestors import AttestorKey, AttestorRegistry
from korpus.security.corpus_governance import CorpusGovernanceProfile, CorpusOperation, CorpusPolicy
from korpus.security.reviewers import ReviewerGrant, ReviewerRegistry

SOURCE = "a" * 64
EVIDENCE = "e" * 64


def test_release_identity_record_and_withdrawal_refuse_invalid_boundary_values() -> None:
    with pytest.raises(ValueError, match="version tag"):
        ReleaseIdentity("0.6.0", SOURCE, EVIDENCE)
    identity = ReleaseIdentity("v0.6.0", SOURCE, EVIDENCE)
    with pytest.raises(ValueError, match="author_subject"):
        ReleaseRecord(identity, ReleaseStage.DRAFT, "")
    with pytest.raises(ValueError, match="require a reason"):
        ReleaseRecord(identity, ReleaseStage.WITHDRAWN, "author")
    with pytest.raises(ValueError, match="non-empty"):
        withdraw(ReleaseRecord(identity, ReleaseStage.RELEASE_CANDIDATE, "author"), "   ")


def test_resilience_parameter_and_half_open_single_probe_boundaries() -> None:
    with pytest.raises(ValueError, match="admission"):
        AdmissionController(0)
    with pytest.raises(ValueError, match="per_subject"):
        AdmissionController(2, per_subject_limit=0)
    with pytest.raises(ValueError, match="circuit breaker"):
        CircuitBreaker(0, 1.0)
    with pytest.raises(ValueError, match="circuit breaker"):
        CircuitBreaker(1, 0.0)

    now = [0.0]
    breaker = CircuitBreaker(1, 1.0, clock=lambda: now[0])
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("trip")))
    now[0] = 2.0
    breaker._half_open_probe = True  # explicit destruction control for the single-probe invariant
    with pytest.raises(CircuitOpenError, match="probe already"):
        breaker.call(lambda: 1)


def _public_policy(*operations: CorpusOperation) -> CorpusPolicy:
    return CorpusPolicy(
        data_owner="Data Owner",
        security_owner="Security Owner",
        rights_reference="RIGHTS-006",
        releasability="internal",
        allowed_classifications=frozenset({Classification.PUBLIC}),
        allowed_authorities=frozenset({AuthorityClass.OFFICIAL_UA}),
        allowed_operations=frozenset(operations),
        retention_days=365,
    )


def _document(classification: Classification = Classification.PUBLIC) -> DocumentCreate:
    return DocumentCreate(
        canonical_title="Governed release source",
        corpus_id="public",
        issuer="Authority",
        access_tier=(AccessTier.RESTRICTED if classification == Classification.RESTRICTED else AccessTier.PUBLIC),
        classification=classification,
    )


def test_corpus_governance_covers_index_classification_empty_and_allowed_embedding() -> None:
    version = VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA)
    no_index = CorpusGovernanceProfile(
        profile_id="gov-no-index",
        corpora={"public": _public_policy(CorpusOperation.CITE)},
    )
    with pytest.raises(PermissionError, match="indexing"):
        no_index.authorize_ingestion(_document(), version, ocr_requested=False)

    profile = CorpusGovernanceProfile(
        profile_id="gov-public",
        corpora={
            "public": _public_policy(
                CorpusOperation.INDEX,
                CorpusOperation.CITE,
                CorpusOperation.EXTERNAL_EMBEDDING,
            )
        },
    )
    with pytest.raises(PermissionError, match="classification"):
        profile.authorize_ingestion(
            _document(Classification.RESTRICTED), version, ocr_requested=False
        )
    with pytest.raises(PermissionError, match="no corpus scope"):
        profile.require_external_embedding(frozenset())
    profile.require_external_embedding(frozenset({"public"}))


def _attestor_key(**updates: object) -> AttestorKey:
    data: dict[str, object] = {
        "key_id": "key-001",
        "organisation": "External Lab",
        "role": "external_assessor",
        "public_key_b64": base64.b64encode(bytes(32)).decode("ascii"),
        "enrolled_by": "risk-owner",
    }
    data.update(updates)
    return AttestorKey(**data)


def test_attestor_registry_refuses_inverted_window_map_mismatch_digest_and_postdate(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="validity interval"):
        _attestor_key(valid_from=date(2026, 2, 1), valid_until=date(2026, 1, 1))

    key = _attestor_key(valid_until=date(2026, 1, 1))
    with pytest.raises(ValidationError, match="key map"):
        AttestorRegistry(registry_id="attestors", keys={"wrong-id": key})

    registry = AttestorRegistry(registry_id="attestors", keys={key.key_id: key})
    path = tmp_path / "attestors.json"
    path.write_text(registry.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        AttestorRegistry.load(path, "f" * 64)

    failure = registry.verify(
        ground_id="external-redteam",
        ground_kind="external_assessment",
        attestation={
            "key_id": key.key_id,
            "signature_b64": base64.b64encode(b"invalid").decode("ascii"),
            "signed_by": "External Lab",
            "signed_at": "2026-02-01",
        },
        document_sha256="c" * 64,
    )
    assert any("postdates" in item for item in failure)


def _records() -> tuple[DocumentRecord, DocumentVersionRecord]:
    document = DocumentRecord(
        canonical_title="Reviewer target",
        corpus_id="public",
        issuer="Authority",
        jurisdiction="UA",
        document_type="order",
        access_tier=AccessTier.PUBLIC,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1",
        source_hash="0" * 64,
        object_key="00/00/" + "0" * 64,
        mime_type="text/plain",
        authority=AuthorityClass.OFFICIAL_UA,
    )
    return document, version


def test_reviewer_grant_refuses_non_review_stage_inverted_window_and_expired_edges() -> None:
    with pytest.raises(ValidationError, match="review stages"):
        ReviewerGrant(
            credential_id="cred-invalid",
            stages=frozenset({ReviewState.REJECTED}),
            corpora=frozenset({"public"}),
            authorities=frozenset({AuthorityClass.OFFICIAL_UA}),
        )
    with pytest.raises(ValidationError, match="inverted"):
        ReviewerGrant(
            credential_id="cred-window",
            stages=frozenset({ReviewState.APPROVED}),
            corpora=frozenset({"public"}),
            authorities=frozenset({AuthorityClass.OFFICIAL_UA}),
            valid_from=date(2026, 2, 1),
            valid_until=date(2026, 1, 1),
        )
    document, version = _records()
    early = ReviewerGrant(
        credential_id="cred-early",
        stages=frozenset({ReviewState.APPROVED}),
        corpora=frozenset({"public"}),
        authorities=frozenset({AuthorityClass.OFFICIAL_UA}),
        valid_from=date(2026, 2, 1),
    )
    late = ReviewerGrant(
        credential_id="cred-late",
        stages=frozenset({ReviewState.APPROVED}),
        corpora=frozenset({"public"}),
        authorities=frozenset({AuthorityClass.OFFICIAL_UA}),
        valid_until=date(2026, 1, 1),
    )
    registry = ReviewerRegistry(registry_id="review-window", subjects={"r": (early, late)})
    with pytest.raises(PermissionError, match="no active"):
        registry.authorize(
            subject="r",
            target=ReviewState.APPROVED,
            document=document,
            version=version,
            as_of=date(2026, 1, 15),
        )
