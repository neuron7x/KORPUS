"""Persisted contextual metadata must bind candidates, cache, answers and audit."""

from __future__ import annotations

import json
from datetime import date

import pytest
from korpus.application.cache import EvidenceQueryCache
from korpus.application.contextual_projection import build_contextual_projection
from korpus.application.retrieval import HybridLexicalRetriever
from korpus.config import get_settings
from korpus.infrastructure.schema import audits, documents, spans, versions
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url

from apps.api.tests.conftest import POSTGRES_ADMIN_URL, privileged_connection, set_identity
from apps.api.tests.helpers import approve, ingest_text

MARKER = "NEUTRALZEPHYR"
BODY = "Архівний запис має містити дату та відповідальну особу."
QUERY = "Що має містити архівний запис?"
CORPORA = frozenset({"public"})


def _persisted_evidence(client, version_id):
    with privileged_connection(client) as connection:
        version = dict(
            connection.execute(select(versions).where(versions.c.id == version_id)).mappings().one()
        )
        evidence = [
            dict(row)
            for row in connection.execute(
                select(spans).where(spans.c.version_id == version_id).order_by(spans.c.ordinal)
            ).mappings()
        ]
    assert version["review_state"] == "approved"
    assert len(str(version["evidence_digest"])) == 64
    assert evidence and all(row["text"] == BODY for row in evidence)
    return version, evidence


def _mutate_metadata(client, identity, document_id, field, database_role):
    repository = client.app.state.repository
    context = (
        repository.engine.begin()
        if database_role == "application"
        else privileged_connection(client)
    )
    with context as connection:
        if database_role == "application":
            repository._apply_postgres_identity(connection, identity)
        if connection.dialect.name == "postgresql":
            principal = connection.execute(
                text(
                    "SELECT current_user, session_user, rolsuper, rolbypassrls, "
                    "pg_has_role(current_user, (SELECT relowner FROM pg_class "
                    "WHERE oid = 'public.documents'::regclass), 'MEMBER') AS owner_member "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
            assert principal.current_user == principal.session_user
            if database_role == "application":
                assert principal.current_user == repository.engine.url.username
                assert not principal.rolsuper and not principal.rolbypassrls
                assert not principal.owner_member
            else:
                assert POSTGRES_ADMIN_URL is not None
                assert principal.current_user == make_url(POSTGRES_ADMIN_URL).username
                assert principal.owner_member
        assert (
            connection.execute(
                select(documents.c.id).where(documents.c.id == document_id)
            ).scalar_one()
            == document_id
        )
        changed = connection.execute(
            update(documents).where(documents.c.id == document_id).values({field: MARKER})
        )
        assert changed.rowcount == 1
        assert (
            connection.execute(
                select(documents.c[field]).where(documents.c.id == document_id)
            ).scalar_one()
            == MARKER
        )


def _answer_and_audit(client, as_of, token, *, query=QUERY, retrieved=1, citations):
    response = client.post(
        "/v1/answers",
        json={"text": query, "as_of": as_of.isoformat(), "corpus_ids": ["public"]},
    )
    assert response.status_code == 200, response.text
    answer = response.json()
    expected_status = "answered" if query == QUERY else "insufficient_evidence"
    assert answer["status"] == expected_status, answer
    assert answer["corpus_release"] == token.release_id
    with privileged_connection(client) as connection:
        payload = connection.execute(
            select(audits.c.payload_json).where(
                audits.c.action == "answer.completed", audits.c.resource_id == answer["id"]
            )
        ).scalar_one()
    event = json.loads(payload)
    assert event["corpus_release"] == token.release_id
    assert event["corpus_snapshot"] == {
        "release_id": token.release_id,
        "state_epoch": token.state_epoch,
        "as_of": as_of.isoformat(),
        "corpus_ids": ["public"],
        "authorization_scope_id": token.authorization_scope_id,
    }
    assert event["retrieved"] == retrieved
    assert event["citations"] == citations
    assert [
        {
            key: citation[key]
            for key in ("document_id", "version_id", "span_id", "revision", "quote_hash")
        }
        for citation in answer["citations"]
    ] == citations
    assert all(MARKER not in citation["quote"] for citation in answer["citations"])


@pytest.mark.parametrize("field", ["issuer", "jurisdiction", "document_type"])
@pytest.mark.parametrize("database_role", ["application", "database-owner"])
def test_contextual_metadata_mutation_rebinds_candidates_cache_and_audit(
    client, admin_identity, public_identity, field, database_role
):
    """Use real SQL and HTTP paths; PostgreSQL also proves the app login is restricted."""
    settings = client.app.dependency_overrides[get_settings]().model_copy(
        update={"contextual_retrieval_enabled": True}
    )
    client.app.dependency_overrides[get_settings] = lambda: settings
    client.app.state.query_cache = EvidenceQueryCache(maximum_entries=8, ttl_seconds=600)
    result = ingest_text(client, title="Archive record", text=BODY)
    version_id, document_id = result["version"]["id"], result["document"]["id"]
    approve(client, version_id)
    original_evidence = _persisted_evidence(client, version_id)
    expected_citations = [
        {
            "document_id": document_id,
            "version_id": version_id,
            "span_id": original_evidence[1][0]["id"],
            "revision": original_evidence[0]["revision"],
            "quote_hash": original_evidence[1][0]["text_hash"],
        }
    ]
    set_identity(client, public_identity)
    repository = client.app.state.repository
    reader = client.app.state.corpus_snapshot_reader
    retriever = HybridLexicalRetriever(
        repository, candidate_budget=8, contextual_projection_enabled=True
    )
    as_of = date.today()
    before = reader.capture(public_identity, CORPORA, as_of)
    original = repository.list_retrievable_spans(public_identity, CORPORA, as_of)
    assert len(original) == 1
    projection_before = build_contextual_projection(*original[0])
    assert retriever.search(public_identity, MARKER, CORPORA, as_of) == []
    for _ in range(2):
        _answer_and_audit(client, as_of, before, citations=expected_citations)
        _answer_and_audit(client, as_of, before, query=MARKER, retrieved=0, citations=[])
    first_stats = client.app.state.query_cache.stats()
    assert (first_stats.misses, first_stats.hits) == (2, 2)

    _mutate_metadata(client, admin_identity, document_id, field, database_role)

    after = reader.capture(public_identity, CORPORA, as_of)
    assert after.release_id != before.release_id
    assert after.state_epoch > before.state_epoch
    assert _persisted_evidence(client, version_id) == original_evidence
    candidates = retriever.search(public_identity, MARKER, CORPORA, as_of)
    assert {str(item.span.id) for item in candidates} == {
        str(row["id"]) for row in original_evidence[1]
    }
    assert {str(item.version.id) for item in candidates} == {version_id}
    assert all(getattr(item.document, field) == MARKER for item in candidates)
    candidate = candidates[0]
    projection_after = build_contextual_projection(
        candidate.span, candidate.document, candidate.version
    )
    assert projection_after.projection_sha256 != projection_before.projection_sha256
    assert projection_after.evidence_sha256 == projection_before.evidence_sha256
    assert projection_after.evidence_text == projection_before.evidence_text == BODY
    for _ in range(2):
        _answer_and_audit(client, as_of, after, citations=expected_citations)
        _answer_and_audit(client, as_of, after, query=MARKER, citations=[])
    final_stats = client.app.state.query_cache.stats()
    assert (final_stats.misses, final_stats.hits) == (4, 4)
