from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select, text

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
from korpus.infrastructure.repository import SqlRepository, spans

POSTGRES_URL = os.getenv("KORPUS_POSTGRES_TEST_URL")
pytestmark = pytest.mark.postgres


@pytest.mark.skipif(not POSTGRES_URL, reason="KORPUS_POSTGRES_TEST_URL is not configured")
def test_postgres_migrated_search_rls_access_and_audit(tmp_path: Path):
    repository = SqlRepository(
        POSTGRES_URL,
        "postgres-integration-audit-key",
        audit_anchor_path=tmp_path / "postgres-anchor.json",
    )
    repository.initialize(create_schema=False)
    with repository.engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT current_user, rolsuper, rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
    assert role.current_user == "korpus_app"
    assert role.rolsuper is False
    assert role.rolbypassrls is False

    actor = Identity(
        subject="postgres-admin",
        roles=frozenset({"admin", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public", "restricted-demo"}),
    )

    def create(corpus: str, tier: AccessTier, classification: Classification, marker: str):
        document = DocumentRecord(
            canonical_title=f"PostgreSQL {corpus} source",
            corpus_id=corpus,
            issuer="Integration Authority",
            jurisdiction="UA",
            document_type="order",
            access_tier=tier,
            classification=classification,
        )
        version = DocumentVersionRecord(
            document_id=document.id,
            revision="1",
            source_hash=("b" if corpus == "public" else "c") * 64,
            object_key=f"integration/{corpus}",
            mime_type="text/plain",
            authority=AuthorityClass.OFFICIAL_UA,
            review_state=ReviewState.APPROVED,
            is_current=True,
        )
        span = EvidenceSpanRecord(
            version_id=version.id,
            ordinal=0,
            text=f"{marker} indexed evidence is retrievable only when authorized.",
        )
        repository.create_document_bundle(
            actor, document, version, [span], {"integration": "postgres", "corpus": corpus}
        )
        return span

    public_span = create("public", AccessTier.PUBLIC, Classification.PUBLIC, "POSTGRES-PUBLIC")
    create(
        "restricted-demo",
        AccessTier.RESTRICTED,
        Classification.RESTRICTED,
        "POSTGRES-RESTRICTED",
    )
    public_identity = Identity(
        subject="postgres-public",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
    )
    result = HybridLexicalRetriever(repository, candidate_budget=8).search(
        public_identity,
        "POSTGRES-PUBLIC indexed evidence",
        public_identity.corpora,
        date.today(),
    )
    assert result and result[0].span.id == public_span.id

    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, public_identity)
        visible_text = connection.execute(select(spans.c.text)).scalars().all()
    assert any("POSTGRES-PUBLIC" in value for value in visible_text)
    assert all("POSTGRES-RESTRICTED" not in value for value in visible_text)
    assert repository.verify_audit().valid is True
