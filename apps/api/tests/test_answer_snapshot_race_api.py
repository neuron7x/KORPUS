"""The default HTTP answer runtime must reject post-retrieval epoch drift."""

from __future__ import annotations

import json

import pytest
from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
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
