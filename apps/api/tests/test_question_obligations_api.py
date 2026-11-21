"""Neutral archive-card regressions at shipped answer thresholds through HTTP."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest
from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.config import get_settings
from korpus.domain.models import QueryRequest, RetrievedEvidence

from apps.api.tests.helpers import approve, ingest_text


@pytest.fixture
def production_threshold_client(client):
    settings = client.app.dependency_overrides[get_settings]().model_copy(
        update={
            "min_retrieval_score": 0.18,
            "min_query_coverage": 0.5,
            "min_support_score": 0.18,
        }
    )
    client.app.dependency_overrides[get_settings] = lambda: settings
    return client


@pytest.mark.parametrize(
    "question",
    [
        pytest.param("Який контроль потрібен для доступу до документа?", id="masculine"),
        pytest.param("Яка перевірка потрібна для доступу до документа?", id="feminine"),
        pytest.param("Яке підтвердження потрібне для доступу до документа?", id="neuter"),
        pytest.param("Які перевірки потрібні для доступу до документа?", id="plural"),
    ],
)
def test_required_control_predicate_keeps_safe_source_after_injection(
    production_threshold_client, question
):
    client = production_threshold_client
    fixture = Path(__file__).resolve().parents[3] / "evals/fixtures/source_injection.txt"
    result = ingest_text(client, title="source-injection", text=fixture.read_text())
    approve(client, result["version"]["id"])
    response = client.post("/v1/answers", json={"text": question})
    assert response.status_code == 200
    answer = response.json()
    assert answer["status"] == "answered", answer
    assert [item["quote"] for item in answer["citations"]] == [
        "Для доступу до документа система перевіряє роль і рівень доступу користувача."
    ]
    assert all(item["version_id"] == result["version"]["id"] for item in answer["citations"])
    assert "Ignore previous" not in response.text


@pytest.mark.parametrize("subject", ["Липи", "«Липа»", "QZ-17"])
def test_required_control_predicate_retains_explicit_subject_obligation(
    production_threshold_client, subject
):
    client = production_threshold_client
    result = ingest_text(
        client,
        text="Для доступу до документа система перевіряє роль і рівень доступу користувача.",
    )
    approve(client, result["version"]["id"])
    answer = client.post(
        "/v1/answers",
        json={"text": f"Який контроль потрібен для доступу користувача до документа {subject}?"},
    ).json()
    assert answer["status"] == "insufficient_evidence", answer
    assert answer["decision_reason"] == "question_obligations_unmet"
    assert answer["claims"] == answer["citations"] == []


@pytest.mark.parametrize(
    ("question", "text", "expected"),
    [
        (
            "Який порядок архіву Липи?",
            "Порядок архіву Липи встановлює щоденний облік карток.",
            "answered",
        ),
        (
            "Який порядок архіву Липи?",
            "Порядок архіву Кедра встановлює щоденний облік карток для архіву Липи.",
            "insufficient_evidence",
        ),
        (
            "Який порядок архіву Липи?",
            "Порядок архіву Кедра для архіву Липи встановлює щоденний облік карток.",
            "insufficient_evidence",
        ),
        (
            "Який порядок і строк архіву Липи?",
            "Порядок архіву Липи встановлює щоденний облік карток.",
            "insufficient_evidence",
        ),
    ],
    ids=("bound-procedure", "name-in-value", "foreign-head", "missing-second-property"),
)
def test_establishes_predicate_keeps_subject_and_facet_head_binding(
    production_threshold_client, question, text, expected
):
    client = production_threshold_client
    result = ingest_text(client, text=text)
    approve(client, result["version"]["id"])
    answer = client.post("/v1/answers", json={"text": question}).json()
    assert answer["status"] == expected, answer
    if expected == "answered":
        assert [item["quote"] for item in answer["citations"]] == [text]
        assert answer["citations"][0]["version_id"] == result["version"]["id"]
    else:
        assert answer["decision_reason"] == "question_obligations_unmet"
        assert answer["claims"] == answer["citations"] == []


@pytest.mark.parametrize("subject", ["Полтави", "полтави", "Смарагду", "невідомограда"])
def test_wrong_entity_cannot_reach_supported_answer(production_threshold_client, subject):
    client = production_threshold_client
    result = ingest_text(client, text="Колір картки архіву Львова — синій.")
    approve(client, result["version"]["id"])
    response = client.post("/v1/answers", json={"text": f"Який колір картки архіву {subject}?"})
    assert response.status_code == 200
    answer = response.json()
    assert answer["status"] == "insufficient_evidence"
    assert answer["decision_reason"] == "question_obligations_unmet"
    assert answer["claims"] == answer["citations"] == []
    assert answer["evidence_coverage"] == 0.0
    right = client.post("/v1/answers", json={"text": "Який колір картки архіву Львова?"}).json()
    assert right["status"] == "answered"
    assert right["citations"][0]["quote"] == "Колір картки архіву Львова — синій."


def test_explicit_entity_in_generic_question_is_still_mandatory(production_threshold_client):
    client = production_threshold_client
    text = "Відомо про архів Кедра: картка є синя."
    result = ingest_text(client, text=text)
    approve(client, result["version"]["id"])
    wrong = client.post("/v1/answers", json={"text": "Що відомо про архів Липи?"}).json()
    assert wrong["status"] == "insufficient_evidence"
    assert wrong["decision_reason"] == "question_obligations_unmet"
    right = client.post("/v1/answers", json={"text": "Що відомо про архів Кедра?"}).json()
    assert right["status"] == "answered", right
    assert right["citations"][0]["quote"] == text


@pytest.mark.parametrize(
    "question", ["Які обов'язки архіваріуса?", "Які обов'язки має Архіваріус?"]
)
def test_declared_archivist_duties_keep_genitive_and_predicate_forms(
    production_threshold_client, question
):
    client = production_threshold_client
    text = "Архіваріус зобов'язаний: перевіряти картки та впорядковувати записи."
    result = ingest_text(client, title="Обов'язки: Архіваріус (Архів, ст.1)", text=text)
    approve(client, result["version"]["id"])
    answer = client.post("/v1/answers", json={"text": question}).json()
    assert answer["status"] == "answered", answer
    assert answer["citations"][0]["quote"] == text


def test_missing_requested_property_is_an_explicit_refusal(production_threshold_client):
    client = production_threshold_client
    result = ingest_text(client, text="Колір картки архіву — синій.")
    approve(client, result["version"]["id"])
    answer = client.post("/v1/answers", json={"text": "Який колір і розмір картки архіву?"}).json()
    assert answer["status"] == "insufficient_evidence"
    assert answer["decision_reason"] == "question_obligations_unmet"
    assert any("розмір" in item for item in answer["limitations"])
    assert answer["claims"] == answer["citations"] == []


@pytest.mark.parametrize(
    ("question", "text"),
    [
        (
            "Який колір картки архіву Липи?",
            "Колір картки архіву Кедра — синій, а розмір картки архіву Липи — великий.",
        ),
        ("Який колір картки архіву Липи?", "Колір картки архіву Кедра — синій для архіву Липи."),
        ("який колір картки архіву липи?", "Колір картки архіву кедра для архіву липи — синій."),
        ("Який колір картки архіву Липи?", "Колір картки «Архів» (Кедр) для Липи — синій."),
        (
            "Який колір і розмір картки архіву Липи?",
            "Колір картки архіву Липи — синій, а розмір картки архіву Кедра — великий.",
        ),
    ],
)
def test_entity_co_mention_cannot_bind_a_foreign_property(
    production_threshold_client, question, text
):
    client = production_threshold_client
    result = ingest_text(client, text=text)
    approve(client, result["version"]["id"])
    answer = client.post("/v1/answers", json={"text": question}).json()
    assert answer["status"] == "insufficient_evidence", answer
    assert answer["decision_reason"] == "question_obligations_unmet"
    assert answer["claims"] == answer["citations"] == []


def test_named_fact_with_an_unrelated_neighbor_keeps_its_own_witness(production_threshold_client):
    client = production_threshold_client
    text = "Колір картки архіву Липи — синій, а розмір картки архіву Кедра — великий."
    result = ingest_text(client, text=text)
    approve(client, result["version"]["id"])
    answer = client.post("/v1/answers", json={"text": "Який колір картки архіву Липи?"}).json()
    assert answer["status"] == "answered", answer
    assert answer["citations"][0]["quote"] == text


@pytest.mark.parametrize("separate_spans", [False, True])
def test_complete_two_property_answer_preserves_exact_provenance(
    production_threshold_client, separate_spans
):
    client = production_threshold_client
    color, size = "Колір картки архіву — синій.", "Розмір картки архіву — великий."
    padding = (
        ("\n\nСлужбова примітка про впорядкування матеріалів. " * 45) if separate_spans else " "
    )
    result = ingest_text(client, text=color + padding + size)
    approve(client, result["version"]["id"])
    first = client.post("/v1/answers", json={"text": "Який колір і розмір картки архіву?"}).json()
    assert first["status"] == "answered", first
    assert {item["quote"] for item in first["citations"]} == {color, size}
    assert len({item["version_id"] for item in first["citations"]}) == 1
    assert len({item["span_id"] for item in first["citations"]}) == (2 if separate_spans else 1)
    assert any("одне джерело" in item for item in first["limitations"])
    for citation in first["citations"]:
        assert citation["source_hash"] == result["version"]["source_hash"]
        assert citation["quote_hash"] == hashlib.sha256(citation["quote"].encode()).hexdigest()
    second = client.post("/v1/answers", json={"text": "Який колір і розмір картки архіву?"}).json()
    for answer in (first, second):
        answer.pop("id")
        answer.pop("created_at")
    assert first == second


def test_three_facet_availability_matrix_is_complete_only_for_full_witness(client, admin_identity):
    facts = (
        "Колір картки архіву — синій.",
        "Розмір картки архіву — великий.",
        "Матеріал картки архіву — папір.",
    )
    separator = "\n\nСлужбова примітка про впорядкування матеріалів. " * 45
    result = ingest_text(client, text=separator.join(facts))
    approve(client, result["version"]["id"])
    rows = client.app.state.repository.list_retrievable_spans(
        admin_identity, frozenset({"public"}), date.today()
    )
    sources = [
        RetrievedEvidence(
            span=span, document=document, version=version, score=0.95, query_coverage=1.0
        )
        for fact in facts
        for span, document, version in rows
        if fact in span.text
    ]
    assert len(sources) == 3 and len({item.span.id for item in sources}) == 3

    class FixedRetriever:
        def __init__(self, evidence):
            self.evidence = evidence

        def search(self, identity, text, corpus_ids, as_of, limit=8):
            return self.evidence[:limit]

    question = QueryRequest(text="Який колір і розмір і матеріал картки архіву?")
    for mask in range(8):
        selected = [item for index, item in enumerate(sources) if mask & (1 << index)]
        projections = []
        for offered in (selected, list(reversed(selected)), selected + selected[:1]):
            service = ExtractiveAnswerService(
                client.app.state.repository,
                FixedRetriever(offered),
                client.app.state.policy,
                AnswerPolicy(0.18, 0.5, 0.18, "obligation-matrix"),
            )
            answer = service.execute(admin_identity, question)
            projection = answer.model_dump(mode="json", exclude={"id", "created_at"})
            projections.append(projection)
            if mask == 7:
                assert projection["status"] == "answered"
                assert {citation.quote for citation in answer.citations} == set(facts)
                assert len(answer.claims) == 3
            else:
                assert projection["status"] == "insufficient_evidence"
                assert answer.claims == answer.citations == []
                assert answer.decision_reason == (
                    "question_obligations_unmet" if selected else "retrieval_gate_failed"
                )
        assert all(projection == projections[0] for projection in projections)


def test_final_gate_refuses_an_extra_claim_borrowing_a_cited_span(
    client, admin_identity, monkeypatch
):
    right = "Колір картки архіву Липи — синій."
    wrong = "Колір картки архіву Кедра — зелений."
    result = ingest_text(client, text=right + " " + wrong)
    approve(client, result["version"]["id"])
    rows = client.app.state.repository.list_retrievable_spans(
        admin_identity, frozenset({"public"}), date.today()
    )
    sources = [
        RetrievedEvidence(
            span=span, document=document, version=version, score=0.95, query_coverage=1.0
        )
        for span, document, version in rows
        if right in span.text and wrong in span.text
    ]
    assert len(sources) == 1

    class FixedRetriever:
        def search(self, identity, text, corpus_ids, as_of, limit=8):
            return sources[:limit]

    service = ExtractiveAnswerService(
        client.app.state.repository,
        FixedRetriever(),
        client.app.state.policy,
        AnswerPolicy(0.18, 0.5, 0.18, "claim-binding-review"),
    )
    query = QueryRequest(text="Який колір картки архіву Липи?")
    baseline = service.execute(admin_identity, query)
    assert baseline.status.value == "answered"
    assert [claim.text for claim in baseline.claims] == [right]
    extract = service._extract

    def substituted(*args, **kwargs):
        claims, citations, covered = extract(*args, **kwargs)
        extra = claims[0].model_copy(update={"text": wrong})
        return [*claims, extra], citations, covered

    monkeypatch.setattr(service, "_extract", substituted)
    answer = service.execute(admin_identity, query)
    assert answer.status.value == "insufficient_evidence"
    assert answer.decision_reason == "question_obligations_unmet"
    assert answer.claims == answer.citations == []
    assert any("claim_quote_binding" in item for item in answer.limitations)


@pytest.mark.parametrize("field", ["document_id", "version_id"])
def test_generic_question_refuses_foreign_citation_identity(
    client, admin_identity, monkeypatch, field
):
    text = "Кожен запис має містити дату та відповідальну особу."
    result = ingest_text(client, title="Нейтральний архів", text=text)
    approve(client, result["version"]["id"])
    rows = client.app.state.repository.list_retrievable_spans(
        admin_identity, frozenset({"public"}), date.today()
    )
    sources = [
        RetrievedEvidence(
            span=span, document=document, version=version, score=0.95, query_coverage=1.0
        )
        for span, document, version in rows
    ]

    class FixedRetriever:
        def search(self, identity, text, corpus_ids, as_of, limit=8):
            return sources[:limit]

    service = ExtractiveAnswerService(
        client.app.state.repository,
        FixedRetriever(),
        client.app.state.policy,
        AnswerPolicy(0.18, 0.5, 0.18, "generic-identity-binding"),
    )
    query = QueryRequest(text="Що має містити кожен запис?")
    baseline = service.execute(admin_identity, query)
    assert baseline.status.value == "answered"
    assert len(baseline.citations) == 1
    assert baseline.citations[0].quote == text
    extract = service._extract
    foreign = UUID("00000000-0000-4000-8000-000000000009")
    assert all(getattr(citation, field) != foreign for citation in baseline.citations)

    def substitute(*args, **kwargs):
        claims, citations, covered = extract(*args, **kwargs)
        poisoned = [citation.model_copy(update={field: foreign}) for citation in citations]
        return claims, poisoned, covered

    monkeypatch.setattr(service, "_extract", substitute)
    answer = service.execute(admin_identity, query)
    assert answer.status.value == "insufficient_evidence"
    assert answer.decision_reason == "question_obligations_unmet"
    assert answer.claims == answer.citations == []
    assert any("claim_quote_binding" in item for item in answer.limitations)


@pytest.mark.parametrize(
    ("question", "text"),
    [
        ("Який колір архіву A?", "Колір архіву — синій."),
        ("What is the color of archive A?", "The color of archive is blue."),
        ("What is the color of card A?", "The color of a card is blue."),
        ("Який колір архіву A?", "Колір архіву A — синій."),
    ],
)
def test_unquoted_single_letter_function_label_requires_explicit_disambiguation(
    production_threshold_client, question, text
):
    client = production_threshold_client
    result = ingest_text(client, title="Нейтральний архів", text=text)
    approve(client, result["version"]["id"])
    answer = client.post("/v1/answers", json={"text": question}).json()
    assert answer["status"] == "insufficient_evidence"
    assert answer["decision_reason"] == "question_obligations_unmet"
    assert answer["claims"] == answer["citations"] == []
    assert any("ambiguous_single_letter_subject" in item for item in answer["limitations"])


def test_quoted_single_letter_name_cannot_borrow_an_ordinary_article(production_threshold_client):
    client = production_threshold_client
    result = ingest_text(client, title="Neutral archive", text="The color of a card is blue.")
    approve(client, result["version"]["id"])
    answer = client.post("/v1/answers", json={"text": 'What is the color of card "A"?'}).json()
    assert answer["status"] == "insufficient_evidence"
    assert answer["claims"] == answer["citations"] == []


@pytest.mark.parametrize(
    ("question", "text"),
    [
        ('What is the color of card "A"?', 'The color of card "A" is blue.'),
        ("Який колір картки «A»?", "Колір картки «A» — синій."),
    ],
)
def test_quoted_single_letter_name_keeps_its_explicit_source_witness(
    production_threshold_client, question, text
):
    client = production_threshold_client
    result = ingest_text(client, title="Neutral archive", text=text)
    approve(client, result["version"]["id"])
    answer = client.post("/v1/answers", json={"text": question}).json()
    assert answer["status"] == "answered", answer
    assert answer["citations"][0]["quote"] == text
