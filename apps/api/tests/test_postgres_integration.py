from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
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
from korpus.infrastructure.repository import (
    SqlRepository,
    documents,
    span_embeddings,
    spans,
    versions,
)
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError

from apps.api.tests.conftest import reset_database

POSTGRES_URL = os.getenv("KORPUS_POSTGRES_TEST_URL")
pytestmark = pytest.mark.postgres


@pytest.mark.skipif(not POSTGRES_URL, reason="KORPUS_POSTGRES_TEST_URL is not configured")
def test_postgres_migrated_search_rls_access_and_audit(tmp_path: Path):
    # This test signs its audit events with its own key, so any event another test
    # left behind reads as a hash mismatch — which is the chain check working, not a
    # finding. It shares the database with the rest of the suite when the whole suite
    # runs on PostgreSQL, so it starts from an empty one.
    reset_database()
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
            review_state=ReviewState.QUARANTINED,
            # An approved version governs from a stated date, in both dialects.
            publication_date=date(2020, 1, 1),
            is_current=False,
        )
        span = EvidenceSpanRecord(
            version_id=version.id,
            ordinal=0,
            text=f"{marker} indexed evidence is retrievable only when authorized.",
        )
        repository.create_document_bundle(
            actor, document, version, [span], {"integration": "postgres", "corpus": corpus}
        )
        # Approval must happen after evidence exists: approval seals the exact persisted
        # evidence digest and the database makes approved evidence immutable thereafter.
        version = repository.transition_version(
            actor,
            version.id,
            ReviewState.QUARANTINED,
            ReviewState.APPROVED,
            "approve PostgreSQL integration fixture after evidence seal",
        )
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, actor)
            epoch_before = int(
                connection.execute(
                    text("SELECT epoch FROM corpus_state_epoch WHERE singleton_id = 1")
                ).scalar_one()
            )
            connection.execute(
                insert(span_embeddings).values(
                    span_id=str(span.id),
                    model_id="integration-model",
                    dimensions=2,
                    embedding_json=json.dumps([0.0, 1.0]),
                    text_hash=span.text_hash,
                    created_at=datetime.now(UTC),
                )
            )
            epoch_after = int(
                connection.execute(
                    text("SELECT epoch FROM corpus_state_epoch WHERE singleton_id = 1")
                ).scalar_one()
            )
        # App DML must advance the migration-owned epoch even though the app role has
        # no UPDATE privilege on corpus_state_epoch itself.
        assert epoch_after == epoch_before + 1
        return document, version, span

    public_document, public_version, public_span = create(
        "public", AccessTier.PUBLIC, Classification.PUBLIC, "POSTGRES-PUBLIC"
    )
    restricted_document, restricted_version, restricted_span = create(
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
        visible_documents = set(connection.execute(select(documents.c.id)).scalars())
        visible_versions = set(connection.execute(select(versions.c.id)).scalars())
        visible_spans = set(connection.execute(select(spans.c.id)).scalars())
        visible_embeddings = set(connection.execute(select(span_embeddings.c.span_id)).scalars())
        readable_epoch = int(
            connection.execute(
                text("SELECT epoch FROM corpus_state_epoch WHERE singleton_id = 1")
            ).scalar_one()
        )
    assert visible_documents == {str(public_document.id)}
    assert visible_versions == {str(public_version.id)}
    assert visible_spans == {str(public_span.id)}
    assert visible_embeddings == {str(public_span.id)}
    assert readable_epoch > 0
    assert str(restricted_document.id) not in visible_documents
    assert str(restricted_version.id) not in visible_versions
    assert str(restricted_span.id) not in visible_spans

    # Missing session identity fails closed across every corpus-bearing table.
    with repository.engine.connect() as connection:
        assert connection.execute(select(documents.c.id)).all() == []
        assert connection.execute(select(versions.c.id)).all() == []
        assert connection.execute(select(spans.c.id)).all() == []
        assert connection.execute(select(span_embeddings.c.span_id)).all() == []

    # Migration-owned state is observable where runtime correctness needs it but never
    # writable by the application role.
    with pytest.raises(DBAPIError), repository.engine.begin() as connection:
        connection.execute(
            text("UPDATE corpus_state_epoch SET epoch = epoch + 100 WHERE singleton_id = 1")
        )

    with pytest.raises(DBAPIError), repository.engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='forged'"))

    assert repository.verify_audit().valid is True
    repository.close()
