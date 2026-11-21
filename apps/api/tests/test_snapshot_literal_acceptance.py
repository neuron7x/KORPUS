"""Literal F/H/I/J/L witnesses use only persisted neutral archive fixtures."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from korpus.application.corpus_snapshot import (
    CorpusConsistencyError,
    release_identity_digest,
    token_audit_record,
    version_evidence_digest,
)
from korpus.application.retrieval import HybridLexicalRetriever
from korpus.domain.models import ExtractedPage
from korpus.infrastructure import retrieval_queries
from korpus.infrastructure.evidence_sealing import seal_evidence_digest
from korpus.infrastructure.extraction import make_spans
from korpus.infrastructure.schema import audits, corpus_state_epoch, spans, versions
from korpus.infrastructure.semantic_release import semantic_release_members
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import DBAPIError

from .conftest import privileged_connection, set_identity
from .helpers import approve, ingest_text, ingest_version

CORPORA = frozenset({"public"})
AS_OF = date(2026, 6, 1)
BODY = "Архівний запис має містити дату та відповідальну особу."
QUESTION = "Що має містити архівний запис?"


def persisted_rows(client, version_id):
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
    return version, evidence


@pytest.mark.parametrize("operation", ("text-only", "ordinal-only"))
def test_approved_text_only_or_reordering_update_is_denied_and_rolled_back(
    client, operation, record_property
):
    source = ingest_text(client, title="Neutral immutable archive", text=(BODY + " ") * 35)
    version_id = source["version"]["id"]
    draft, rows = persisted_rows(client, version_id)
    assert draft["evidence_digest"] is None and len(rows) >= 2
    first = rows[0]
    changes = (
        {"text": first["text"] + " changed alone"}
        if operation == "text-only"
        else {"ordinal": max(row["ordinal"] for row in rows) + 10}
    )
    assert "text_hash" not in changes
    # The same exact operation is writable on a draft; denial is not a broken SQL fixture.
    with privileged_connection(client) as connection:
        result = connection.execute(
            update(spans).where(spans.c.id == first["id"]).values(**changes)
        )
        assert result.rowcount == 1
    changed = persisted_rows(client, version_id)[1]
    if operation == "ordinal-only":
        assert changed[-1]["id"] == first["id"] and changed[0]["id"] != first["id"]
    else:
        assert changed[0]["text_hash"] == first["text_hash"]
        assert changed[0]["text"] != first["text"]
    with privileged_connection(client) as connection:
        connection.execute(
            update(spans)
            .where(spans.c.id == first["id"])
            .values(**{name: first[name] for name in changes})
        )
    assert persisted_rows(client, version_id) == (draft, rows)
    approve(client, version_id)
    sealed = persisted_rows(client, version_id)
    with pytest.raises(DBAPIError, match="immutable"), privileged_connection(client) as connection:
        connection.execute(update(spans).where(spans.c.id == first["id"]).values(**changes))
    assert persisted_rows(client, version_id) == sealed
    record_property(
        "native_immutability",
        json.dumps(
            {
                "dialect": client.app.state.repository.engine.dialect.name,
                "operation": operation,
                "draft_write": True,
                "sealed_write_denied": True,
                "post_rollback_rows_equal": True,
                "fixture_role": "database-owner boundary",
            },
            sort_keys=True,
        ),
    )


def install_layout(connection, version_id, pieces, stamp):
    connection.execute(delete(spans).where(spans.c.version_id == version_id))
    values = [
        {
            "id": str(uuid5(NAMESPACE_URL, version_id + ":" + str(piece["ordinal"]))),
            "version_id": version_id,
            "created_at": stamp,
            **piece,
            "text_hash": hashlib.sha256(str(piece["text"]).encode()).hexdigest(),
        }
        for piece in pieces
    ]
    connection.execute(insert(spans), values)
    return values


def test_same_raw_source_and_ids_with_new_derived_layout_change_seal_and_release(
    client, public_identity, record_property
):
    raw = "Archive card records the date and custodian. " * 8
    source = ingest_text(client, title="Neutral derivation archive", text=raw)
    version_id = source["version"]["id"]
    original, _ = persisted_rows(client, version_id)
    assert original["source_hash"] == hashlib.sha256(raw.encode()).hexdigest()
    layouts = [
        make_spans([ExtractedPage(page=None, text=raw)], max_chars=size, overlap_chars=0)
        for size in (180, 230)
    ]
    assert len(layouts[0]) == len(layouts[1]) == 2 and layouts[0] != layouts[1]
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    with privileged_connection(client) as connection:
        first = install_layout(connection, version_id, layouts[0], stamp)
        digest_a = seal_evidence_digest(connection, UUID(version_id))
        assert seal_evidence_digest(connection, UUID(version_id)) == digest_a
        reversed_digest = version_evidence_digest(
            (row["id"], row["ordinal"], row["page"], row["section"], row["text"], row["text_hash"])
            for row in reversed(first)
        )
        assert reversed_digest == digest_a
        second = install_layout(connection, version_id, layouts[1], stamp)
        digest_b = seal_evidence_digest(connection, UUID(version_id))
        assert [row["id"] for row in first] == [row["id"] for row in second]
        assert digest_b != digest_a
    after, _ = persisted_rows(client, version_id)
    assert after == original
    approve(client, version_id)
    with privileged_connection(client) as connection:
        visible = connection.execute(
            retrieval_queries.release_projection(public_identity, CORPORA, AS_OF)
        )
        members = semantic_release_members(connection, list(visible.mappings()))
    assert len(members) == 1
    member_b = members[0]
    assert member_b.version_id == version_id
    assert member_b.document_id == source["document"]["id"]
    assert member_b.source_hash == original["source_hash"]
    assert member_b.evidence_digest == digest_b
    member_a = replace(member_b, evidence_digest=digest_a)
    assert release_identity_digest([member_a]) != release_identity_digest([member_b])
    assert client.app.state.corpus_snapshot_reader.capture(
        public_identity, CORPORA, AS_OF
    ).release_id == release_identity_digest([member_b])
    record_property(
        "native_derivation_identity",
        json.dumps(
            {
                "dialect": client.app.state.repository.engine.dialect.name,
                "raw_source_sha256": original["source_hash"],
                "same_document_version_span_ids": True,
                "evidence_digest_a": digest_a,
                "evidence_digest_b": digest_b,
                "only_semantic_member_difference": "evidence_digest",
            },
            sort_keys=True,
        ),
    )


def read_audit(client, answer):
    with privileged_connection(client) as connection:
        raw = connection.execute(
            select(audits.c.payload_json).where(
                audits.c.action == "answer.completed", audits.c.resource_id == answer["id"]
            )
        ).scalar_one()
    return json.loads(raw)


def test_historical_http_answer_binds_exact_old_citations_release_and_audit_token(
    client, public_identity
):
    first = ingest_text(client, title="Archive history", text=BODY, effective_from=date(2025, 1, 1))
    approve(client, first["version"]["id"])
    second = ingest_version(
        client,
        first["document"]["id"],
        revision="2",
        text="Архівний запис має містити реєстраційний номер та назву колекції.",
        supersedes_version_id=first["version"]["id"],
        effective_from=date(2026, 1, 1),
    )
    approve(client, second["version"]["id"])
    set_identity(client, public_identity)
    repository, reader = client.app.state.repository, client.app.state.corpus_snapshot_reader
    releases = []
    for as_of, version in ((date(2025, 6, 1), first["version"]), (AS_OF, second["version"])):
        token = reader.capture(public_identity, CORPORA, as_of)
        expected = repository.list_retrievable_spans(public_identity, CORPORA, as_of)
        assert expected and {str(row[2].id) for row in expected} == {version["id"]}
        response = client.post(
            "/v1/answers",
            json={"text": QUESTION, "corpus_ids": ["public"], "as_of": as_of.isoformat()},
        )
        assert response.status_code == 200, response.text
        answer = response.json()
        assert answer["status"] == "answered", answer
        assert answer["corpus_release"] == token.release_id
        assert {citation["span_id"] for citation in answer["citations"]} == {
            str(row[0].id) for row in expected
        }
        by_id = {str(row[0].id): row for row in expected}
        for citation in answer["citations"]:
            span, document, stored_version = by_id[citation["span_id"]]
            assert citation["document_id"] == str(document.id)
            assert citation["version_id"] == str(stored_version.id) == version["id"]
            assert citation["source_hash"] == stored_version.source_hash
            assert citation["span_hash"] == span.text_hash
            assert citation["quote"] == span.text[citation["quote_start"] : citation["quote_end"]]
            assert citation["quote_hash"] == hashlib.sha256(citation["quote"].encode()).hexdigest()
        event = read_audit(client, answer)
        assert event["corpus_release"] == token.release_id
        assert event["corpus_snapshot"] == token_audit_record(token)
        assert event["citations"] == [
            {
                name: citation[name]
                for name in ("document_id", "version_id", "span_id", "revision", "quote_hash")
            }
            for citation in answer["citations"]
        ]
        releases.append(token.release_id)
    assert releases[0] != releases[1]


def assert_native_capture_and_http_refuse(client, identity, monkeypatch, reason):
    reader = client.app.state.corpus_snapshot_reader
    with pytest.raises(CorpusConsistencyError, match=reason):
        reader.capture(identity, CORPORA, AS_OF)
    retrieval_calls = []

    def unexpected_retrieval(*_args, **_kwargs):
        retrieval_calls.append(True)
        raise AssertionError("retrieval ran after native snapshot capture failure")

    monkeypatch.setattr(HybridLexicalRetriever, "search", unexpected_retrieval)
    monkeypatch.setattr(HybridLexicalRetriever, "search_with_semantic", unexpected_retrieval)
    set_identity(client, identity)
    response = client.post(
        "/v1/answers", json={"text": QUESTION, "as_of": AS_OF.isoformat(), "corpus_ids": ["public"]}
    )
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["status"] == "insufficient_evidence"
    assert answer["decision_reason"] == "corpus_snapshot_unavailable"
    assert answer["corpus_release"] == "unnamed"
    assert answer["citations"] == answer["claims"] == retrieval_calls == []
    event = read_audit(client, answer)
    assert event["corpus_snapshot"] is None and event["corpus_release"] == "unnamed"


@pytest.mark.parametrize("digest", (None, "z" * 64), ids=("missing", "malformed"))
def test_native_missing_or_malformed_seal_cannot_support_a_read(
    client, public_identity, monkeypatch, record_property, digest
):
    source = ingest_text(client, title="Neutral unsealed archive", text=BODY)
    version_id = source["version"]["id"]
    before = persisted_rows(client, version_id)
    assert before[0]["evidence_digest"] is None
    dialect = client.app.state.repository.engine.dialect.name
    statement = (
        update(versions)
        .where(versions.c.id == version_id)
        .values(review_state="approved", is_current=True, evidence_digest=digest)
    )
    if dialect == "postgresql" and digest is None:
        with (
            pytest.raises(DBAPIError, match="ck_approved_version_evidence_digest"),
            privileged_connection(client) as connection,
        ):
            connection.execute(statement)
        assert persisted_rows(client, version_id) == before
        record_property(
            "native_seal_refusal",
            "PostgreSQL NULL rejected by migrated CHECK before read; no corrupt row created",
        )
        return
    with privileged_connection(client) as connection:
        assert connection.execute(statement).rowcount == 1
    assert persisted_rows(client, version_id)[0]["evidence_digest"] == digest
    assert_native_capture_and_http_refuse(
        client, public_identity, monkeypatch, "no valid evidence digest"
    )
    record_property(
        "native_seal_refusal",
        json.dumps(
            {
                "dialect": dialect,
                "fault": "missing" if digest is None else "nonhex",
                "ordinary_privileged_fixture_dml": True,
                "guards_altered": False,
                "native_capture_refused": True,
                "http_refused_without_token": True,
            },
            sort_keys=True,
        ),
    )


def test_native_missing_epoch_row_refuses_capture_and_http(
    client, public_identity, monkeypatch, record_property
):
    source = ingest_text(client, title="Neutral epoch archive", text=BODY)
    approve(client, source["version"]["id"])
    client.app.state.corpus_snapshot_reader.capture(public_identity, CORPORA, AS_OF)
    with privileged_connection(client) as connection:
        assert (
            connection.execute(
                delete(corpus_state_epoch).where(corpus_state_epoch.c.singleton_id == 1)
            ).rowcount
            == 1
        )
    assert_native_capture_and_http_refuse(
        client, public_identity, monkeypatch, "epoch is not initialized"
    )
    record_property(
        "native_epoch_refusal",
        json.dumps(
            {
                "dialect": client.app.state.repository.engine.dialect.name,
                "deleted_singleton_rows": 1,
                "native_capture_refused": True,
                "http_refused_without_token": True,
                "guards_altered": False,
            },
            sort_keys=True,
        ),
    )
