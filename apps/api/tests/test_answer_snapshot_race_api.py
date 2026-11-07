"""The default HTTP answer runtime must reject post-retrieval epoch drift."""

from __future__ import annotations

import json

import pytest
from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.corpus_snapshot import (
    CorpusConsistencyError,
    ReleaseIdentityUnavailable,
)
from korpus.application.retrieval import HybridLexicalRetriever
from korpus.domain.models import AnswerStatus, QueryRequest
from korpus.infrastructure.schema import audits
from sqlalchemy import select

from apps.api.tests.conftest import privileged_connection
from apps.api.tests.helpers import approve, ingest_text


def test_final_answer_and_audit_refuse_composition_time_approval(
    client, admin_identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = ingest_text(client)
    approve(client, first["version"]["id"])
    pending = ingest_text(
        client,
        title="New version arrives during composition",
        text="Нове затвердження змінює стан корпусу після завершення пошуку.",
    )
    pending_id = pending["version"]["id"]
    service = ExtractiveAnswerService(
        client.app.state.repository,
        HybridLexicalRetriever(client.app.state.repository, candidate_budget=8),
        client.app.state.policy,
        AnswerPolicy(0.1, 0.1, 0.1, "snapshot-race-control"),
    )
    query = QueryRequest(text="Що має містити кожен запис?")
    baseline = service.execute(admin_identity, query)
    assert baseline.status is AnswerStatus.ANSWERED
    mutated = []

    def approve_before_audit(query, claims, eligible):
        approve(client, pending_id)
        mutated.append(True)
        return None, "controlled approval interleaving"

    monkeypatch.setattr(service, "_compose", approve_before_audit)
    answer = service.execute(admin_identity, query)
    assert mutated == [True]
    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert answer.decision_reason == "corpus_snapshot_changed"
    assert answer.citations == []
    assert answer.claims == []

    with privileged_connection(client) as connection:
        payload = connection.execute(
            select(audits.c.payload_json)
            .where(audits.c.action == "answer.completed")
            .order_by(audits.c.sequence.desc())
            .limit(1)
        ).scalar_one()
    event = json.loads(payload)
    assert event["decision_reason"] == "corpus_snapshot_changed"
    assert event["corpus_release"] == answer.corpus_release
    assert event["corpus_snapshot"]["release_id"] == answer.corpus_release


def test_final_answer_refuses_rescission_during_composition(
    client, admin_identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = ingest_text(client)
    version_id = first["version"]["id"]
    approve(client, version_id)
    service = ExtractiveAnswerService(
        client.app.state.repository,
        HybridLexicalRetriever(client.app.state.repository, candidate_budget=8),
        client.app.state.policy,
        AnswerPolicy(0.1, 0.1, 0.1, "snapshot-rescission-control"),
    )
    query = QueryRequest(text="Що має містити кожен запис?")
    baseline = service.execute(admin_identity, query)
    assert baseline.status is AnswerStatus.ANSWERED
    changed = []

    def rescind_before_audit(query, claims, eligible):
        response = client.post(
            f"/v1/document-versions/{version_id}/rescission",
            json={"note": "deterministic active-answer rescission control"},
        )
        assert response.status_code == 200, response.text
        changed.append(True)
        return None, "controlled rescission interleaving"

    monkeypatch.setattr(service, "_compose", rescind_before_audit)
    answer = service.execute(admin_identity, query)
    assert changed == [True]
    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert answer.decision_reason == "corpus_snapshot_changed"
    assert answer.citations == []
    assert answer.claims == []


def test_reentrant_answer_restores_outer_audit_snapshot(
    client, admin_identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ingest_text(client)
    approve(client, source["version"]["id"])
    service = ExtractiveAnswerService(
        client.app.state.repository,
        HybridLexicalRetriever(client.app.state.repository, candidate_budget=8),
        client.app.state.policy,
        AnswerPolicy(0.1, 0.1, 0.1, "reentrant-snapshot-control"),
    )
    outer_query = QueryRequest(text="Що має містити кожен запис?", corpus_ids=["public"])
    nested_query = QueryRequest(
        text="Що містить тренувальний корпус?",
        corpus_ids=["training"],
        as_of=outer_query.as_of,
    )
    assert service.execute(admin_identity, outer_query).status is AnswerStatus.ANSWERED
    original_compose = service._compose
    nested_releases: list[str] = []

    def compose_with_nested_read(query, claims, eligible):
        monkeypatch.setattr(service, "_compose", original_compose)
        try:
            nested_releases.append(service.execute(admin_identity, nested_query).corpus_release)
        finally:
            monkeypatch.setattr(service, "_compose", compose_with_nested_read)
        return original_compose(query, claims, eligible)

    monkeypatch.setattr(service, "_compose", compose_with_nested_read)
    answer = service.execute(admin_identity, outer_query)
    assert answer.status is AnswerStatus.ANSWERED
    assert nested_releases and nested_releases[0] != answer.corpus_release

    with privileged_connection(client) as connection:
        payload = connection.execute(
            select(audits.c.payload_json)
            .where(audits.c.action == "answer.completed")
            .order_by(audits.c.sequence.desc())
            .limit(1)
        ).scalar_one()
    event = json.loads(payload)
    assert event["corpus_release"] == answer.corpus_release
    assert event["corpus_snapshot"]["release_id"] == answer.corpus_release
    assert event["corpus_snapshot"]["corpus_ids"] == ["public"]
    assert service._snapshot_token.get() is None


def test_human_review_citations_fail_closed_after_rescission_before_audit(
    client, admin_identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ingest_text(client)
    version_id = source["version"]["id"]
    approve(client, version_id)
    service = ExtractiveAnswerService(
        client.app.state.repository,
        HybridLexicalRetriever(client.app.state.repository, candidate_budget=8),
        client.app.state.policy,
        AnswerPolicy(0.1, 0.1, 0.1, "human-review-snapshot-race"),
    )
    query = QueryRequest(text="Що має містити кожен запис?")
    baseline = service.execute(admin_identity, query)
    assert baseline.status is AnswerStatus.ANSWERED
    assert baseline.citations

    monkeypatch.setattr(service, "_find_contradiction", lambda *_: "controlled contradiction")
    original_block = service._blocked_answer
    mutation_count = []

    def review_then_rescind(*args, **kwargs):
        blocked = original_block(*args, **kwargs)
        assert blocked is not None
        assert blocked.status is AnswerStatus.REQUIRES_HUMAN_REVIEW
        assert blocked.citations
        response = client.post(
            f"/v1/document-versions/{version_id}/rescission",
            json={"note": "source rescinded before human review evidence emission"},
        )
        assert response.status_code == 200, response.text
        mutation_count.append(True)
        return blocked

    monkeypatch.setattr(service, "_blocked_answer", review_then_rescind)
    result = service.execute(admin_identity, query)
    assert mutation_count == [True]
    assert result.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.decision_reason == "corpus_snapshot_changed"
    assert result.citations == []
    assert result.claims == []

@pytest.mark.parametrize(
    "capture_error",
    [
        CorpusConsistencyError("forced epoch mismatch at capture"),
        ReleaseIdentityUnavailable("forced missing snapshot reader"),
    ],
    ids=("consistency-error", "release-reader-missing"),
)
def test_initial_snapshot_capture_failure_abstains_without_retrieval(
    client, admin_identity, monkeypatch: pytest.MonkeyPatch, capture_error: RuntimeError
) -> None:
    repository = client.app.state.repository
    retriever = HybridLexicalRetriever(repository, candidate_budget=8)
    service = ExtractiveAnswerService(
        repository,
        retriever,
        client.app.state.policy,
        AnswerPolicy(0.1, 0.1, 0.1, "initial-snapshot-failure-control"),
    )
    retrieval_calls: list[bool] = []

    def reject_retrieval(*_args, **_kwargs):
        retrieval_calls.append(True)
        raise AssertionError("retrieval ran without a captured corpus snapshot")

    def fail_capture(*_args):
        raise capture_error

    monkeypatch.setattr(retriever, "search", reject_retrieval)
    monkeypatch.setattr(service, "_capture_snapshot", fail_capture)
    answer = service.execute(admin_identity, QueryRequest(text="Що має містити кожен запис?"))

    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert answer.decision_reason == "corpus_snapshot_unavailable"
    assert answer.corpus_release == "unnamed"
    assert answer.citations == []
    assert answer.claims == []
    assert retrieval_calls == []
    assert service._snapshot_token.get() is None

    with privileged_connection(client) as connection:
        payload = connection.execute(
            select(audits.c.payload_json)
            .where(audits.c.action == "answer.completed")
            .order_by(audits.c.sequence.desc())
            .limit(1)
        ).scalar_one()
    event = json.loads(payload)
    assert event["decision_reason"] == "corpus_snapshot_unavailable"
    assert event["corpus_release"] == "unnamed"
    assert event["corpus_snapshot"] is None
