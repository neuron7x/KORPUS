from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError

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
    document_compartments,
    documents,
    span_embeddings,
    spans,
    versions,
)

POSTGRES_URL = os.getenv("KORPUS_POSTGRES_TEST_URL")
POSTGRES_APP_ROLE = os.getenv("KORPUS_POSTGRES_APP_ROLE", "korpus_app")
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
                "SELECT current_user, rolsuper, rolbypassrls, rolcreatedb, "
                "rolcreaterole, rolinherit FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
    assert role.current_user == POSTGRES_APP_ROLE
    assert role.rolsuper is False
    assert role.rolbypassrls is False
    assert role.rolcreatedb is False
    assert role.rolcreaterole is False
    assert role.rolinherit is False

    actor = Identity(
        subject="postgres-admin",
        roles=frozenset({"admin", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public", "restricted-demo"}),
        compartments=frozenset({"omega"}),
    )

    def create(
        corpus: str,
        tier: AccessTier,
        classification: Classification,
        marker: str,
        compartments=frozenset(),
    ):
        document = DocumentRecord(
            canonical_title=f"PostgreSQL {corpus} source",
            corpus_id=corpus,
            issuer="Integration Authority",
            jurisdiction="UA",
            document_type="order",
            access_tier=tier,
            classification=classification,
            compartments=compartments,
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
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, actor)
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
    compartment_document, _, _ = create(
        "restricted-demo",
        AccessTier.RESTRICTED,
        Classification.RESTRICTED,
        "POSTGRES-COMPARTMENT",
        frozenset({"omega"}),
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
        visible_compartments = set(
            connection.execute(
                select(
                    document_compartments.c.document_id,
                    document_compartments.c.compartment,
                )
            ).all()
        )
    assert visible_documents == {str(public_document.id)}
    assert visible_versions == {str(public_version.id)}
    assert visible_spans == {str(public_span.id)}
    assert visible_embeddings == {str(public_span.id)}
    assert visible_compartments == set()
    assert str(restricted_document.id) not in visible_documents
    assert str(restricted_version.id) not in visible_versions
    assert str(restricted_span.id) not in visible_spans

    for compartments, expected in (
        (frozenset(), False),
        (frozenset({"other"}), False),
        (frozenset({"omega"}), True),
    ):
        identity = Identity(
            subject="postgres-restricted",
            roles=frozenset({"user"}),
            clearance=AccessTier.RESTRICTED,
            corpora=frozenset({"restricted-demo"}),
            compartments=compartments,
        )
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, identity)
            visible = str(compartment_document.id) in set(
                connection.execute(select(documents.c.id)).scalars()
            )
            visible_compartment_rows = set(
                connection.execute(
                    select(
                        document_compartments.c.document_id,
                        document_compartments.c.compartment,
                    ).where(
                        document_compartments.c.document_id
                        == str(compartment_document.id)
                    )
                ).all()
            )
        assert visible is expected
        assert bool(visible_compartment_rows) is expected
        if expected:
            assert visible_compartment_rows == {(str(compartment_document.id), "omega")}

    # Missing session identity fails closed across every corpus-bearing table.
    with repository.engine.connect() as connection:
        assert connection.execute(select(documents.c.id)).all() == []
        assert connection.execute(select(versions.c.id)).all() == []
        assert connection.execute(select(spans.c.id)).all() == []
        assert connection.execute(select(span_embeddings.c.span_id)).all() == []
        assert connection.execute(select(document_compartments.c.document_id)).all() == []

    # The application role can read but cannot forge migration state.
    with pytest.raises(DBAPIError):
        with repository.engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num='forged'"))
    with pytest.raises(DBAPIError):
        with repository.engine.begin() as connection:
            connection.execute(text("CREATE TABLE app_role_must_not_create(id integer)"))

    # IAM-006 is deliberately a detection test: arbitrary app-role SQL can broaden GUC claims.
    with repository.engine.begin() as connection:
        connection.execute(text("SELECT set_config('korpus.clearance','3',true)"))
        connection.execute(text("SELECT set_config('korpus.corpora','restricted-demo',true)"))
        connection.execute(text("SELECT set_config('korpus.classifications','restricted',true)"))
        connection.execute(text("SELECT set_config('korpus.compartments','omega',true)"))
        assert (
            connection.execute(
                text("SELECT count(*) FROM documents WHERE corpus_id='restricted-demo'")
            ).scalar_one()
            > 0
        )

    assert repository.verify_audit().valid is True
    repository.close()
