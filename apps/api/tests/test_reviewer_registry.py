from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest
from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.policy import PolicyEngine
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentCreate,
    DocumentRecord,
    DocumentVersionRecord,
    Identity,
    ReviewState,
    ReviewTransition,
    VersionCreate,
)
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.infrastructure.repository import SqlRepository
from korpus.security.reviewers import ReviewerGrant, ReviewerRegistry


def _identity(subject: str) -> Identity:
    return Identity(
        subject=subject,
        roles=frozenset({"admin", "curator", "reviewer", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )


def _registry(*, revoked: bool = False, corpus: str = "public") -> ReviewerRegistry:
    subjects = {}
    for subject, credential, stage in (
        ("metadata-reviewer", "cred-metadata", ReviewState.METADATA_REVIEWED),
        ("content-reviewer", "cred-content", ReviewState.CONTENT_REVIEWED),
        ("approver", "cred-approver", ReviewState.APPROVED),
    ):
        subjects[subject] = (
            ReviewerGrant(
                credential_id=credential,
                stages=frozenset({stage}),
                corpora=frozenset({corpus}),
                authorities=frozenset({AuthorityClass.OFFICIAL_UA}),
                revoked=revoked,
            ),
        )
    return ReviewerRegistry(registry_id="reviewers-v1", subjects=subjects)


def test_registry_digest_revocation_and_scope_are_fail_closed(tmp_path: Path):
    registry = _registry()
    path = tmp_path / "reviewers.json"
    raw = registry.model_dump_json().encode("utf-8")
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="digest mismatch"):
        ReviewerRegistry.load(path, "0" * 64)
    loaded = ReviewerRegistry.load(path, hashlib.sha256(raw).hexdigest())

    document = DocumentRecord(
        canonical_title="Review target",
        corpus_id="public",
        issuer="Authorized Test Authority",
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
    assert loaded.authorize(
        subject="approver", target=ReviewState.APPROVED, document=document, version=version
    ) == "cred-approver"
    with pytest.raises(PermissionError, match="no active reviewer credential"):
        _registry(revoked=True).authorize(
            subject="approver", target=ReviewState.APPROVED, document=document, version=version
        )
    with pytest.raises(PermissionError, match="no active reviewer credential"):
        _registry(corpus="other").authorize(
            subject="approver", target=ReviewState.APPROVED, document=document, version=version
        )


def test_governed_review_records_stage_specific_credential_ids(tmp_path: Path):
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'review.db'}",
        audit_hmac_key="review-audit-key",
        policy=PolicyEngine(),
        audit_anchor_path=tmp_path / "audit-anchor.json",
    )
    repository.initialize(create_schema=True)
    service = IngestionService(
        repository,
        LocalObjectStore(tmp_path / "objects"),
        PolicyEngine(),
        ExtractionSettings(False, "ukr+eng"),
        review_separation_required=True,
        reviewer_registry=_registry(),
        require_reviewer_credentials=True,
    )
    try:
        ingest_actor = _identity("ingestor")
        result = service.ingest(
            ingest_actor,
            DocumentCreate(
                canonical_title="Governed directive",
                corpus_id="public",
                issuer="Authorized Test Authority",
                jurisdiction="UA",
                document_type="order",
                access_tier=AccessTier.PUBLIC,
            ),
            VersionCreate(
                revision="1",
                authority=AuthorityClass.OFFICIAL_UA,
                publication_date=date(2020, 1, 1),
            ),
            "directive.txt",
            "text/plain",
            "Виконати перевірку журналу та зафіксувати результат відповідальною особою.".encode(),
        )

        with pytest.raises(PermissionError, match="no active reviewer credential"):
            service.transition(
                _identity("ingestor"),
                result.version.id,
                ReviewTransition(
                    target=ReviewState.METADATA_REVIEWED,
                    note="unauthorized review",
                    acknowledge_extraction_quality=True,
                    acknowledge_near_duplicate=True,
                ),
            )

        metadata = service.transition(
            _identity("metadata-reviewer"),
            result.version.id,
            ReviewTransition(
                target=ReviewState.METADATA_REVIEWED,
                note="metadata verified",
                acknowledge_extraction_quality=True,
                acknowledge_near_duplicate=True,
            ),
        )
        content = service.transition(
            _identity("content-reviewer"),
            result.version.id,
            ReviewTransition(target=ReviewState.CONTENT_REVIEWED, note="content verified"),
        )
        approved = service.transition(
            _identity("approver"),
            result.version.id,
            ReviewTransition(target=ReviewState.APPROVED, note="approval completed"),
        )
        assert metadata.metadata_reviewer_credential_id == "cred-metadata"
        assert content.content_reviewer_credential_id == "cred-content"
        assert approved.approver_credential_id == "cred-approver"
        assert repository.verify_audit().valid is True
    finally:
        repository.close()


def test_required_registry_cannot_be_omitted(tmp_path: Path):
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'required.db'}",
        audit_hmac_key="required-audit-key",
        policy=PolicyEngine(),
        audit_anchor_path=tmp_path / "required-anchor.json",
    )
    repository.initialize(create_schema=True)
    try:
        with pytest.raises(ValueError, match="requires a registry"):
            IngestionService(
                repository,
                LocalObjectStore(tmp_path / "required-objects"),
                PolicyEngine(),
                ExtractionSettings(False, "ukr+eng"),
                require_reviewer_credentials=True,
            )
    finally:
        repository.close()
