from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentCreate,
    VersionCreate,
)
from korpus.security.corpus_governance import (
    CorpusGovernanceProfile,
    CorpusOperation,
    CorpusPolicy,
)


def _policy(*, operations: frozenset[CorpusOperation]) -> CorpusPolicy:
    return CorpusPolicy(
        data_owner="Data Owner",
        security_owner="Security Owner",
        rights_reference="RIGHTS-001",
        releasability="internal-only",
        allowed_classifications=frozenset({Classification.PUBLIC}),
        allowed_authorities=frozenset({AuthorityClass.OFFICIAL_UA}),
        allowed_operations=operations,
        retention_days=365,
    )


def test_corpus_governance_is_content_addressed_and_fail_closed(tmp_path: Path):
    profile = CorpusGovernanceProfile(
        profile_id="governance-v1",
        corpora={
            "public": _policy(operations=frozenset({CorpusOperation.INDEX, CorpusOperation.CITE}))
        },
    )
    path = tmp_path / "governance.json"
    raw = profile.model_dump_json().encode("utf-8")
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="digest mismatch"):
        CorpusGovernanceProfile.load(path, "0" * 64)
    loaded = CorpusGovernanceProfile.load(path, hashlib.sha256(raw).hexdigest())
    with pytest.raises(PermissionError, match="no approved governance policy"):
        loaded.policy_for("missing")


def test_ingestion_authority_classification_ocr_and_egress_are_governed():
    profile = CorpusGovernanceProfile(
        profile_id="governance-v1",
        corpora={
            "public": _policy(operations=frozenset({CorpusOperation.INDEX, CorpusOperation.CITE}))
        },
    )
    document = DocumentCreate(
        canonical_title="Governed",
        corpus_id="public",
        issuer="Authority",
        access_tier=AccessTier.PUBLIC,
        classification=Classification.PUBLIC,
    )
    version = VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA)
    profile.authorize_ingestion(document, version, ocr_requested=False)
    with pytest.raises(PermissionError, match="does not permit OCR"):
        profile.authorize_ingestion(document, version, ocr_requested=True)
    with pytest.raises(PermissionError, match="authority class"):
        profile.authorize_ingestion(
            document,
            version.model_copy(update={"authority": AuthorityClass.ANALYTICAL}),
            ocr_requested=False,
        )
    with pytest.raises(PermissionError, match="external embedding"):
        profile.require_external_embedding(frozenset({"public"}))


def test_legal_hold_cannot_enable_deletion():
    with pytest.raises(ValueError, match="legal hold"):
        _policy(operations=frozenset({CorpusOperation.INDEX, CorpusOperation.DELETE})).model_copy(
            update={"legal_hold": True},
            deep=True,
        ).model_validate(
            {
                **_policy(
                    operations=frozenset({CorpusOperation.INDEX, CorpusOperation.DELETE})
                ).model_dump(),
                "legal_hold": True,
            }
        )
