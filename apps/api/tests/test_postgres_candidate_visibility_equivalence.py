"""Prove bounded candidate visibility on a real PostgreSQL database."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.evidence_sealing import seal_evidence_digest
from korpus.infrastructure.retrieval_queries import (
    candidate_span_query,
    retrievable_projection,
)
from korpus.infrastructure.rls_repository import RlsBoundSqlRepository
from korpus.infrastructure.schema import (
    document_compartments,
    documents,
    spans,
    versions,
)
from sqlalchemy import create_engine, insert, update

from apps.api.tests.conftest import reset_database

APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL")
ADMIN_URL = os.getenv("KORPUS_TEST_DATABASE_ADMIN_URL")
AUTHZ_URL = os.getenv("KORPUS_AUTHZ_DATABASE_URL")
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not all((APP_URL, ADMIN_URL, AUTHZ_URL)),
        reason="real PostgreSQL app/admin/authz identities required",
    ),
]

AS_OF = date(2026, 8, 14)
CREATED = datetime(2026, 1, 1, tzinfo=UTC)
CORPORA = frozenset({"public"})
READER = Identity(
    subject="candidate-pg-reader",
    roles=frozenset({"user"}),
    clearance=AccessTier.PUBLIC,
    corpora=CORPORA,
)


def _document(connection, *, compartments: tuple[str, ...] = ()) -> str:
    document_id = str(uuid4())
    connection.execute(
        insert(documents).values(
            id=document_id,
            canonical_title="PostgreSQL candidate admission control",
            corpus_id="public",
            issuer="Verifier",
            jurisdiction="UA",
            document_type="order",
            access_tier=0,
            classification="public",
            compartments_json=json.dumps(list(compartments)),
            created_at=CREATED,
        )
    )
    for compartment in compartments:
        connection.execute(
            insert(document_compartments).values(document_id=document_id, compartment=compartment)
        )
    return document_id


def _version(
    connection, document_id: str, body: str, *, supersedes: str | None = None
) -> tuple[str, str]:
    version_id, span_id = str(uuid4()), str(uuid4())
    connection.execute(
        insert(versions).values(
            id=version_id,
            document_id=document_id,
            revision="1",
            source_hash=sha256(body.encode()).hexdigest(),
            evidence_digest=None,
            object_key=f"tests/{version_id}",
            mime_type="text/plain",
            authority="official_ua",
            review_state="content_reviewed",
            publication_date=date(2020, 1, 1),
            effective_from=date(2020, 1, 1),
            supersedes_version_id=supersedes,
            is_current=False,
            created_at=CREATED,
        )
    )
    connection.execute(
        insert(spans).values(
            id=span_id,
            version_id=version_id,
            ordinal=0,
            text=body,
            text_hash=sha256(body.encode()).hexdigest(),
            created_at=CREATED,
        )
    )
    connection.execute(
        update(versions)
        .where(versions.c.id == version_id)
        .values(
            review_state="approved",
            is_current=True,
            evidence_digest=seal_evidence_digest(connection, UUID(version_id)),
        )
    )
    return version_id, span_id


def _observe(
    repository, identity: Identity, query: str, *, limit: int = 1
) -> tuple[set[str], list[str]]:
    built = candidate_span_query(identity, CORPORA, AS_OF, query, limit, "postgresql")
    assert built is not None
    statement, parameters = built
    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, identity)
        canonical = {
            str(row["span_id"])
            for row in connection.execute(
                retrievable_projection(identity, CORPORA, AS_OF)
            ).mappings()
        }
        candidates = [
            str(row["span_id"]) for row in connection.execute(statement, parameters).mappings()
        ]
    assert set(candidates) <= canonical, "candidate query escaped canonical visibility"
    return canonical, candidates


def _repository():
    assert APP_URL and AUTHZ_URL
    return RlsBoundSqlRepository(APP_URL, "candidate-pg-test-key", authz_database_url=AUTHZ_URL)


def test_postgres_foreign_supersession_cannot_suppress_visible_candidate() -> None:
    reset_database()
    assert ADMIN_URL
    admin = create_engine(ADMIN_URL, future=True)
    try:
        with admin.begin() as connection:
            victim = _document(connection)
            foreign = _document(connection)
            victim_version, victim_span = _version(connection, victim, "quasar")
            _version(connection, foreign, "unrelated", supersedes=victim_version)
    finally:
        admin.dispose()
    repository = _repository()
    try:
        canonical, candidates = _observe(repository, READER, "quasar")
        assert victim_span in canonical
        assert candidates == [victim_span]
    finally:
        repository.close()


def test_postgres_invisible_compartments_cannot_exhaust_candidate_limit() -> None:
    reset_database()
    assert ADMIN_URL
    admin = create_engine(ADMIN_URL, future=True)
    try:
        with admin.begin() as connection:
            hidden_spans: set[str] = set()
            for _ in range(6):
                hidden = _document(connection, compartments=("alpha",))
                hidden_spans.add(_version(connection, hidden, "orbit orbit orbit")[1])
            visible_span = _version(connection, _document(connection), "orbit")[1]
    finally:
        admin.dispose()
    repository = _repository()
    try:
        canonical, candidates = _observe(repository, READER, "orbit", limit=1)
        assert visible_span in canonical
        assert not (canonical & hidden_spans)
        assert candidates == [visible_span]
        authorized = READER.model_copy(update={"compartments": frozenset({"alpha"})})
        allowed, selected = _observe(repository, authorized, "orbit", limit=1)
        assert hidden_spans <= allowed
        assert selected and selected[0] in hidden_spans
    finally:
        repository.close()


def test_postgres_partial_compartment_assignment_is_not_admission() -> None:
    reset_database()
    assert ADMIN_URL
    admin = create_engine(ADMIN_URL, future=True)
    try:
        with admin.begin() as connection:
            alpha_span = _version(
                connection, _document(connection, compartments=("alpha",)), "beacon"
            )[1]
            both_span = _version(
                connection,
                _document(connection, compartments=("alpha", "bravo")),
                "beacon beacon beacon",
            )[1]
    finally:
        admin.dispose()
    repository = _repository()
    try:
        alpha = READER.model_copy(update={"compartments": frozenset({"alpha"})})
        canonical, candidates = _observe(repository, alpha, "beacon", limit=1)
        assert alpha_span in canonical
        assert both_span not in canonical
        assert candidates == [alpha_span]
        both = READER.model_copy(update={"compartments": frozenset({"alpha", "bravo"})})
        allowed, selected = _observe(repository, both, "beacon", limit=1)
        assert {alpha_span, both_span} <= allowed
        assert selected == [both_span]
    finally:
        repository.close()
