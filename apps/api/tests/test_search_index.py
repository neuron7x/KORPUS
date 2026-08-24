from __future__ import annotations

from datetime import date

from korpus.application.retrieval import HybridLexicalRetriever

from apps.api.tests.helpers import approve, ingest_text


def test_retrieval_uses_database_candidate_index_not_full_scan(client, monkeypatch):
    result = ingest_text(client, text="INDEX-MARKER база використовує кандидатний пошук.")
    approve(client, result["version"]["id"])
    repository = client.app.state.repository

    def forbidden_full_scan(*args, **kwargs):
        raise AssertionError("full corpus scan entered retrieval path")

    monkeypatch.setattr(repository, "list_retrievable_spans", forbidden_full_scan)
    retriever = HybridLexicalRetriever(repository, candidate_budget=8)
    results = retriever.search(
        client.identity_provider.current,
        "INDEX-MARKER кандидатний пошук",
        frozenset({"public"}),
        date.today(),
    )
    assert results
    assert "INDEX-MARKER" in results[0].span.text


def test_database_candidate_budget_is_a_hard_upper_bound(client):
    for index in range(12):
        result = ingest_text(
            client,
            title=f"Indexed document {index}",
            text=f"BUDGET-MARKER спільний термін документа {index}.",
        )
        approve(client, result["version"]["id"])
    repository = client.app.state.repository
    candidates = repository.search_retrievable_spans(
        client.identity_provider.current,
        frozenset({"public"}),
        date.today(),
        "BUDGET-MARKER спільний термін",
        candidate_limit=8,
    )
    assert 1 <= len(candidates) <= 8
    assert all("BUDGET-MARKER" in span.text for span, _, _ in candidates)


def test_contextual_candidate_fill_recovers_title_vocabulary_without_mutating_evidence(client):
    title = "КВАНТ-РЕЗЕРВ спеціальний протокол"
    body = "Кожен запис має містити дату та відповідальну особу."
    result = ingest_text(client, title=title, text=body)
    approve(client, result["version"]["id"])
    repository = client.app.state.repository
    query = "КВАНТ-РЕЗЕРВ протокол"

    baseline = HybridLexicalRetriever(repository, candidate_budget=8).search(
        client.identity_provider.current,
        query,
        frozenset({"public"}),
        date.today(),
    )
    contextual = HybridLexicalRetriever(
        repository,
        candidate_budget=8,
        contextual_projection_enabled=True,
    ).search(
        client.identity_provider.current,
        query,
        frozenset({"public"}),
        date.today(),
    )

    assert baseline == []
    assert contextual
    assert len(contextual) <= 8
    assert contextual[0].document.canonical_title == title
    assert contextual[0].span.text == body
    assert "КВАНТ-РЕЗЕРВ" not in contextual[0].span.text
