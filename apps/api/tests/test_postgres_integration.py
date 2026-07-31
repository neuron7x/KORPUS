from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from korpus.application.retrieval import HybridLexicalRetriever
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    ReviewState,
)
from korpus.infrastructure.repository import SqlRepository

POSTGRES_URL = os.getenv("KORPUS_POSTGRES_TEST_URL")
pytestmark = pytest.mark.postgres


@pytest.mark.skipif(not POSTGRES_URL, reason="KORPUS_POSTGRES_TEST_URL is not configured")
def test_postgres_migrated_search_access_and_audit(tmp_path: Path):
    repository = SqlRepository(
        POSTGRES_URL,
        "postgres-integration-audit-key",
        audit_anchor_path=tmp_path / "postgres-anchor.json",
    )
    repository.initialize(create_schema=False)
    actor = Identity(
        subject="postgres-admin",
        roles=frozenset({"admin", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )
    document = DocumentRecord(
        canonical_title="PostgreSQL indexed source",
        corpus_id="public",
        issuer="Integration Authority",
        jurisdiction="UA",
        document_type="order",
        access_tier=AccessTier.PUBLIC,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1",
        source_hash="b" * 64,
        object_key="integration/postgres",
        mime_type="text/plain",
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.APPROVED,
        is_current=True,
    )
    span = EvidenceSpanRecord(
        version_id=version.id,
        ordinal=0,
        text="POSTGRES-MARKER indexed evidence is retrievable after migration.",
    )
    repository.create_document_bundle(
        actor,
        document,
        version,
        [span],
        {"integration": "postgres"},
    )
    result = HybridLexicalRetriever(repository, candidate_budget=8).search(
        actor,
        "POSTGRES-MARKER indexed evidence",
        actor.corpora,
        date.today(),
    )
    assert result and result[0].span.id == span.id
    assert repository.verify_audit().valid is True
