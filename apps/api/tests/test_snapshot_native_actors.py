"""A/B/C/D/E with separate native connections and deterministic event handoffs."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Event

import pytest
from korpus.application import retrieval_hybrid
from korpus.application.answer_request_snapshot import RequestBoundRetriever
from korpus.application.cache import CachedRetriever, EvidenceQueryCache
from korpus.application.corpus_snapshot import CorpusConsistencyError, token_audit_record
from korpus.application.pec_cache import PECCachedRetriever
from korpus.application.retrieval import HybridLexicalRetriever, RetrievalWeights
from korpus.domain.models import RetrievedEvidence
from korpus.infrastructure.schema import audits, documents, spans, versions
from sqlalchemy import select, update

from .conftest import privileged_connection, set_identity
from .helpers import approve, ingest_text, transition
from .snapshot_actor_fixtures import TIMEOUT, NativeActors, approve_in_connection
from .test_read_scope_boundaries import MODES, ObservedEntries

AS_OF = date(2026, 6, 1)
CORPORA = frozenset({"public"})
BODY = "Архівний запис має містити дату та відповідальну особу."
QUESTION = "Що має містити архівний запис?"


def pending_version(client, *, body="BETACARD belongs to the second archive record."):
    result = ingest_text(client, title="Neutral pending archive", text=body)
    for state in ("metadata_reviewed", "content_reviewed"):
        transition(client, result["version"]["id"], state)
    return result


def answer(client):
    response = client.post(
        "/v1/answers",
        json={"text": QUESTION, "as_of": AS_OF.isoformat(), "corpus_ids": ["public"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def audit_payload(client, result):
    with privileged_connection(client) as connection:
        raw = connection.execute(
            select(audits.c.payload_json).where(
                audits.c.action == "answer.completed", audits.c.resource_id == result["id"]
            )
        ).scalar_one()
    return json.loads(raw)


def test_native_writer_failure_is_propagated_after_connection_cleanup(client, admin_identity):
    repository = client.app.state.repository
    original = ValueError("neutral native writer failure")

    def mutate(connection):
        connection.execute(select(versions.c.id).limit(1)).all()
        raise original

    actors = NativeActors(repository, admin_identity, mutate)

    def read():
        client.app.state.corpus_snapshot_reader.capture(admin_identity, CORPORA, AS_OF)
        actors.pause_reader()

    with pytest.raises(ExceptionGroup, match="native snapshot actors failed") as failures:
        actors.run(read)
    assert original in failures.value.exceptions
    assert not actors.completed_commit and not actors.active
    assert actors.reader_finished.is_set()


def test_native_actor_accounting_excludes_unrelated_background_connection(client, admin_identity):
    repository = client.app.state.repository
    start, ready, release = Event(), Event(), Event()
    actors = NativeActors(
        repository,
        admin_identity,
        lambda connection: connection.execute(select(versions.c.id)).all(),
    )

    def background():
        assert start.wait(TIMEOUT)
        with repository.engine.connect() as connection:
            connection.execute(select(versions.c.id)).all()
            connection.commit()
            ready.set()
            assert release.wait(TIMEOUT)

    def read():
        start.set()
        assert ready.wait(TIMEOUT)
        client.app.state.corpus_snapshot_reader.capture(admin_identity, CORPORA, AS_OF)
        actors.pause_reader()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="unrelated-native") as pool:
        unrelated = pool.submit(background)
        try:
            actors.run(read)
        finally:
            start.set()
            release.set()
            unrelated.result(timeout=TIMEOUT * 3)
    assert actors.unscoped_checkouts >= 1 and not actors.active


def test_native_actor_held_connection_is_still_refused_at_handoff(client, admin_identity):
    repository = client.app.state.repository
    actors = NativeActors(repository, admin_identity, lambda _connection: None)

    def read():
        with repository.engine.connect() as connection:
            connection.execute(select(versions.c.id)).all()
            actors.pause_reader()

    with pytest.raises(ExceptionGroup) as failures:
        actors.run(read)
    assert any(
        isinstance(error, AssertionError) and "retained a DB connection" in str(error)
        for error in failures.value.exceptions
    )
    assert not actors.completed_commit and not actors.active


def test_native_actor_invalidated_connection_is_accounted_as_returned(client, admin_identity):
    repository = client.app.state.repository
    actors = NativeActors(
        repository,
        admin_identity,
        lambda connection: connection.execute(select(versions.c.id)).all(),
    )

    def read():
        with repository.engine.connect() as connection:
            connection.execute(select(versions.c.id)).all()
            connection.invalidate()
        actors.pause_reader()

    actors.run(read)
    assert actors.completed_commit and not actors.active


@pytest.mark.parametrize("change", ("approval", "rescission", "aba"))
def test_native_writer_commits_while_answer_reader_is_paused(
    client, admin_identity, public_identity, monkeypatch, record_property, change
):
    first = ingest_text(client, title="Neutral archive", text=BODY)
    approve(client, first["version"]["id"])
    pending = pending_version(client) if change == "approval" else None
    repository, snapshot = client.app.state.repository, client.app.state.corpus_snapshot_reader
    set_identity(client, public_identity)
    stable = answer(client)
    assert stable["status"] == "answered" and stable["citations"]
    token_a = snapshot.capture(public_identity, CORPORA, AS_OF)

    def mutate(connection):
        if change == "approval":
            approve_in_connection(connection, repository, admin_identity, pending["version"]["id"])
        elif change == "rescission":
            changed = connection.execute(
                update(versions)
                .where(
                    versions.c.id == first["version"]["id"], versions.c.review_state == "approved"
                )
                .values(rescinded_at=datetime(2026, 1, 1, tzinfo=UTC))
            )
            assert changed.rowcount == 1
        else:
            identifier = first["document"]["id"]
            for issuer in ("Neutral transient issuer", first["document"]["issuer"]):
                repository._apply_postgres_identity(connection, admin_identity)
                changed = connection.execute(
                    update(documents).where(documents.c.id == identifier).values(issuer=issuer)
                )
                assert changed.rowcount == 1
                connection.commit()

    actors = NativeActors(repository, admin_identity, mutate, review_writer=change == "approval")
    original_capture, captured = snapshot.capture, []

    def capture_then_pause(*args):
        token = original_capture(*args)
        captured.append(token)
        actors.pause_reader()
        return token

    with monkeypatch.context() as patch:
        patch.setattr(snapshot, "capture", capture_then_pause)
        result = actors.run(lambda: answer(client))
    assert captured == [token_a]
    assert result["status"] == "insufficient_evidence"
    assert result["decision_reason"] == "corpus_snapshot_changed"
    assert result["citations"] == result["claims"] == []
    event = audit_payload(client, result)
    assert result["corpus_release"] == event["corpus_release"] == token_a.release_id
    assert event["corpus_snapshot"] == token_audit_record(token_a)
    assert event["citations"] == []
    after = snapshot.capture(public_identity, CORPORA, AS_OF)
    assert after.state_epoch > token_a.state_epoch
    assert (after.release_id == token_a.release_id) is (change == "aba")
    if change == "aba":
        assert after.state_epoch >= token_a.state_epoch + 2
    record_property("native_actor_observation", json.dumps(actors.observation(), sort_keys=True))


@pytest.mark.parametrize("mode", MODES)
def test_native_approved_b_is_never_inserted_under_captured_cache_a(
    client, admin_identity, public_identity, record_property, mode
):
    pending = pending_version(client)
    version_id = pending["version"]["id"]
    repository, snapshot = client.app.state.repository, client.app.state.corpus_snapshot_reader
    token_a = snapshot.capture(public_identity, CORPORA, AS_OF)
    actors = NativeActors(
        repository,
        admin_identity,
        lambda conn: approve_in_connection(conn, repository, admin_identity, version_id),
        review_writer=True,
    )
    observed = []

    class NativeDelegate:
        def search(self, identity, text, corpora, as_of, limit=8):
            actors.pause_reader()
            rows = repository.search_retrievable_spans(identity, corpora, as_of, text, limit)
            observed.extend(str(version.id) for _span, _document, version in rows)
            assert observed == [version_id]
            return [
                RetrievedEvidence(
                    span=span, document=document, version=version, score=1.0, query_coverage=1.0
                )
                for span, document, version in rows
            ]

        def search_with_semantic(self, *args, semantic_enabled):
            return self.search(*args)

    cache = EvidenceQueryCache()
    cache._entries = ObservedEntries()
    kind = CachedRetriever if mode == "baseline" else PECCachedRetriever
    cached = kind(repository, NativeDelegate(), cache, "native-captured-token")
    bound = RequestBoundRetriever(repository, cached, token_a)

    def read():
        with pytest.raises(CorpusConsistencyError):
            if mode in {"baseline", "pec-default"}:
                bound.search(public_identity, "BETACARD", CORPORA, AS_OF)
            else:
                bound.search_with_semantic(
                    public_identity,
                    "BETACARD",
                    CORPORA,
                    AS_OF,
                    semantic_enabled=mode == "pec-semantic",
                )

    actors.run(read)
    assert observed == [version_id]
    assert cache._entries.insertions == [] and cache.stats().entries == 0
    assert snapshot.capture(public_identity, CORPORA, AS_OF).release_id != token_a.release_id
    record_property("native_actor_observation", json.dumps(actors.observation(), sort_keys=True))


def test_native_nonempty_semantic_backfill_never_reaches_ranking_after_drift(
    client, admin_identity, public_identity, monkeypatch, record_property
):
    first = ingest_text(client, title="Neutral lexical record", text="ALPHACARD archive record.")
    approve(client, first["version"]["id"])
    pending = pending_version(client)
    repository, snapshot = client.app.state.repository, client.app.state.corpus_snapshot_reader
    with privileged_connection(client) as connection:
        second_span = connection.execute(
            select(spans.c.id).where(spans.c.version_id == pending["version"]["id"])
        ).scalar_one()
    actors = NativeActors(
        repository,
        admin_identity,
        lambda conn: approve_in_connection(
            conn, repository, admin_identity, pending["version"]["id"]
        ),
        review_writer=True,
    )
    pause = [True]

    class Semantic:
        def search(self, *_args):
            if pause[0]:
                actors.pause_reader()
            return [(__import__("uuid").UUID(second_span), 0.9)]

    original_backfill = repository.get_retrievable_spans_by_ids
    backfilled = []

    def backfill(*args):
        rows = original_backfill(*args)
        backfilled.append([str(span.id) for span, _document, _version in rows])
        return rows

    monkeypatch.setattr(repository, "get_retrievable_spans_by_ids", backfill)
    original_score, scored = retrieval_hybrid.score_candidates, []

    def score(*args, **kwargs):
        scored.append(list(args[1]))
        return original_score(*args, **kwargs)

    monkeypatch.setattr(retrieval_hybrid, "score_candidates", score)
    delegate = HybridLexicalRetriever(
        repository,
        candidate_budget=8,
        semantic_source=Semantic(),
        weights=RetrievalWeights(
            lexical=0.32,
            semantic=0.10,
            query_coverage=0.24,
            character=0.10,
            authority=0.14,
            phrase=0.06,
            temporal=0.04,
        ),
    )
    token_a = snapshot.capture(public_identity, CORPORA, AS_OF)
    bound = RequestBoundRetriever(repository, delegate, token_a)

    def read():
        with pytest.raises(CorpusConsistencyError):
            bound.search(public_identity, "ALPHACARD", CORPORA, AS_OF)

    actors.run(read)
    assert backfilled == [[second_span]] and scored == []
    pause[0] = False
    fresh = RequestBoundRetriever(
        repository, delegate, snapshot.capture(public_identity, CORPORA, AS_OF)
    )
    result = fresh.search(public_identity, "ALPHACARD", CORPORA, AS_OF)
    assert len(scored) == 1 and len(scored[0]) == 2
    assert {str(item.version.id) for item in result} == {
        first["version"]["id"],
        pending["version"]["id"],
    }
    record_property("native_actor_observation", json.dumps(actors.observation(), sort_keys=True))
