from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.tests.helpers import approve, ingest_text
from korpus.application.corpus_snapshot import CorpusConsistencyError, version_evidence_digest
from korpus.application.retrieval import HybridLexicalRetriever, RetrievalWeights
from korpus.application.snapshot_retrieval import SnapshotBoundRetriever
from korpus.infrastructure.schema import audits, span_embeddings, spans, versions


def _version_id(result: dict[str, object]) -> str:
    version = result["version"]
    assert isinstance(version, dict)
    identifier = version["id"]
    assert isinstance(identifier, str)
    return identifier


class _MutateBeforeSearch:
    """Deterministic call-boundary barrier: mutate after token check, before delegate read."""

    def __init__(self, mutation: Callable[[], None], delegate: HybridLexicalRetriever) -> None:
        self.mutation = mutation
        self.delegate = delegate
        self.result = []

    def search(self, identity, text, corpus_ids, as_of, limit=8):
        self.mutation()
        self.result = self.delegate.search(identity, text, corpus_ids, as_of, limit)
        return self.result


class _MutateAfterSearch:
    """Deterministic call-boundary barrier: mutate after read, before token revalidation."""

    def __init__(self, mutation: Callable[[], None], delegate: HybridLexicalRetriever) -> None:
        self.mutation = mutation
        self.delegate = delegate
        self.result = []

    def search(self, identity, text, corpus_ids, as_of, limit=8):
        self.result = self.delegate.search(identity, text, corpus_ids, as_of, limit)
        self.mutation()
        return self.result


class _MutationSemanticSource:
    """The hybrid retriever calls this only after its lexical repository read."""

    def __init__(self, mutation: Callable[[], None]) -> None:
        self.mutation = mutation
        self.called = False

    def search(self, identity, text, corpus_ids, as_of, limit):
        self.called = True
        self.mutation()
        return []


def test_approval_seals_the_exact_persisted_evidence_set(client, admin_identity) -> None:
    result = ingest_text(client)
    version_id = _version_id(result)
    approve(client, version_id)
    repository = client.app.state.repository

    with repository.engine.begin() as connection:
        stored_digest = connection.execute(
            select(versions.c.evidence_digest).where(versions.c.id == version_id)
        ).scalar_one()
        rows = connection.execute(
            select(
                spans.c.id,
                spans.c.ordinal,
                spans.c.page,
                spans.c.section,
                spans.c.text,
                spans.c.text_hash,
            )
            .where(spans.c.version_id == version_id)
            .order_by(spans.c.ordinal, spans.c.id)
        ).mappings().all()

    expected = version_evidence_digest(
        (
            str(row["id"]),
            int(row["ordinal"]),
            None if row["page"] is None else int(row["page"]),
            None if row["section"] is None else str(row["section"]),
            str(row["text"]),
            str(row["text_hash"]),
        )
        for row in rows
    )
    assert stored_digest == expected

    reader = client.app.state.corpus_snapshot_reader
    as_of = datetime.now(UTC).date()
    token = reader.capture(admin_identity, frozenset({"public"}), as_of)
    assert len(token.release_id) == 64
    assert all(character in "0123456789abcdef" for character in token.release_id)
    reader.validate(admin_identity, frozenset({"public"}), as_of, token)


def test_approved_evidence_and_its_seal_are_database_immutable(client) -> None:
    result = ingest_text(client)
    version_id = _version_id(result)
    approve(client, version_id)
    repository = client.app.state.repository

    with repository.engine.begin() as connection:
        span = connection.execute(
            select(spans)
            .where(spans.c.version_id == version_id)
            .order_by(spans.c.ordinal)
            .limit(1)
        ).mappings().one()

    changed_text = f"{span['text']} tampered"
    changed_hash = hashlib.sha256(changed_text.encode("utf-8")).hexdigest()
    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                update(spans)
                .where(spans.c.id == span["id"])
                .values(text=changed_text, text_hash=changed_hash)
            )

    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                insert(spans).values(
                    id=str(uuid4()),
                    version_id=version_id,
                    ordinal=999_999,
                    page=None,
                    section=None,
                    text="injected after approval",
                    text_hash=hashlib.sha256(b"injected after approval").hexdigest(),
                    created_at=datetime.now(UTC),
                )
            )

    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(delete(spans).where(spans.c.id == span["id"]))

    with pytest.raises(IntegrityError):
        with repository.engine.begin() as connection:
            connection.execute(
                update(versions)
                .where(versions.c.id == version_id)
                .values(evidence_digest="0" * 64)
            )


def test_approval_between_token_validation_and_retrieval_fails_closed(
    client, admin_identity
) -> None:
    first = ingest_text(client, title="Race A", text="Маркер ALPHA-RACE чинний до зміни стану.")
    approve(client, _version_id(first))
    second = ingest_text(client, title="Race B", text="Маркер BRAVO-RACE з'являється лише після схвалення.")
    second_version = _version_id(second)

    repository = client.app.state.repository
    reader = client.app.state.corpus_snapshot_reader
    corpora = frozenset({"public"})
    as_of = datetime.now(UTC).date()
    token_a = reader.capture(admin_identity, corpora, as_of)
    delegate = HybridLexicalRetriever(repository, candidate_budget=8)
    interleaved = _MutateBeforeSearch(
        lambda: approve(client, second_version),
        delegate,
    )
    bound = SnapshotBoundRetriever(reader, interleaved)

    with pytest.raises(CorpusConsistencyError):
        bound.search(
            admin_identity,
            "BRAVO-RACE з'являється після схвалення",
            corpora,
            as_of,
            token_a,
        )
    assert interleaved.result
    assert any(str(item.version.id) == second_version for item in interleaved.result)


def test_rescission_after_retrieval_before_revalidation_fails_closed(
    client, admin_identity
) -> None:
    result = ingest_text(
        client,
        title="Rescission race",
        text="Маркер RESCIND-RACE наказує зберігати цей запис.",
    )
    version_id = _version_id(result)
    approve(client, version_id)

    repository = client.app.state.repository
    reader = client.app.state.corpus_snapshot_reader
    corpora = frozenset({"public"})
    as_of = datetime.now(UTC).date()
    token_a = reader.capture(admin_identity, corpora, as_of)
    delegate = HybridLexicalRetriever(repository, candidate_budget=8)

    def rescind() -> None:
        response = client.post(
            f"/v1/document-versions/{version_id}/rescission",
            json={"note": "deterministic rescission race"},
        )
        assert response.status_code == 200, response.text

    interleaved = _MutateAfterSearch(rescind, delegate)
    bound = SnapshotBoundRetriever(reader, interleaved)

    with pytest.raises(CorpusConsistencyError):
        bound.search(
            admin_identity,
            "RESCIND-RACE зберігати цей запис",
            corpora,
            as_of,
            token_a,
        )
    assert interleaved.result
    assert any(str(item.version.id) == version_id for item in interleaved.result)


def test_lexical_then_state_change_before_semantic_phase_fails_closed(
    client, admin_identity
) -> None:
    first = ingest_text(
        client,
        title="Lexical A",
        text="Маркер LEXICAL-RACE присутній у початковому корпусі.",
    )
    approve(client, _version_id(first))
    second = ingest_text(
        client,
        title="Semantic B",
        text="Маркер SEMANTIC-RACE стає доступним лише після схвалення.",
    )
    second_version = _version_id(second)

    repository = client.app.state.repository
    reader = client.app.state.corpus_snapshot_reader
    corpora = frozenset({"public"})
    as_of = datetime.now(UTC).date()
    token_a = reader.capture(admin_identity, corpora, as_of)
    semantic = _MutationSemanticSource(lambda: approve(client, second_version))
    delegate = HybridLexicalRetriever(
        repository,
        candidate_budget=8,
        semantic_source=semantic,
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
    bound = SnapshotBoundRetriever(reader, delegate)

    with pytest.raises(CorpusConsistencyError):
        bound.search(
            admin_identity,
            "LEXICAL-RACE початковому корпусі",
            corpora,
            as_of,
            token_a,
        )
    assert semantic.called is True


def test_semantic_backfill_invalidates_an_inflight_snapshot_token(
    client, admin_identity
) -> None:
    result = ingest_text(client)
    version_id = _version_id(result)
    approve(client, version_id)
    repository = client.app.state.repository
    reader = client.app.state.corpus_snapshot_reader
    as_of = datetime.now(UTC).date()
    corpora = frozenset({"public"})
    token_before = reader.capture(admin_identity, corpora, as_of)

    with repository.engine.begin() as connection:
        span = connection.execute(
            select(spans.c.id, spans.c.text_hash)
            .where(spans.c.version_id == version_id)
            .order_by(spans.c.ordinal)
            .limit(1)
        ).mappings().one()
        connection.execute(
            insert(span_embeddings).values(
                span_id=span["id"],
                model_id="snapshot-race-control",
                dimensions=2,
                embedding_json="[0.0,1.0]",
                text_hash=span["text_hash"],
                created_at=datetime.now(UTC),
            )
        )

    token_after = reader.capture(admin_identity, corpora, as_of)
    assert token_after.release_id == token_before.release_id
    assert token_after.state_epoch > token_before.state_epoch
    with pytest.raises(CorpusConsistencyError):
        reader.validate(admin_identity, corpora, as_of, token_before)


def test_monotonic_epoch_kills_release_aba_without_changing_historical_identity(
    client, admin_identity
) -> None:
    first = ingest_text(client, title="A", text="Маркер ALPHA наказує вести журнал щоденно.")
    first_version = _version_id(first)
    approve(client, first_version)
    reader = client.app.state.corpus_snapshot_reader
    as_of = datetime.now(UTC).date()
    corpora = frozenset({"public"})
    token_a = reader.capture(admin_identity, corpora, as_of)

    second = ingest_text(client, title="B", text="Маркер BRAVO наказує подати рапорт негайно.")
    second_version = _version_id(second)
    approve(client, second_version)
    token_b = reader.capture(admin_identity, corpora, as_of)
    assert token_b.release_id != token_a.release_id
    assert token_b.state_epoch > token_a.state_epoch

    response = client.post(
        f"/v1/document-versions/{second_version}/rescission",
        json={"note": "withdrawn by issuing authority for deterministic ABA control"},
    )
    assert response.status_code == 200, response.text

    token_a_again = reader.capture(admin_identity, corpora, as_of)
    assert token_a_again.release_id == token_a.release_id
    assert token_a_again.state_epoch > token_b.state_epoch
    with pytest.raises(CorpusConsistencyError):
        reader.validate(admin_identity, corpora, as_of, token_a)


def test_answer_and_audit_commit_to_the_same_snapshot_release(client) -> None:
    result = ingest_text(client)
    approve(client, _version_id(result))

    response = client.post("/v1/answers", json={"text": "Що має містити кожен запис?"})
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["status"] == "answered"

    repository = client.app.state.repository
    with repository.engine.begin() as connection:
        payload = connection.execute(
            select(audits.c.payload_json)
            .where(audits.c.action == "answer.completed")
            .order_by(audits.c.sequence.desc())
            .limit(1)
        ).scalar_one()
    event = json.loads(payload)
    snapshot = event["corpus_snapshot"]
    assert snapshot is not None
    assert snapshot["release_id"] == answer["corpus_release"]
    assert event["corpus_release"] == answer["corpus_release"]
    assert snapshot["as_of"] == event["as_of"]
