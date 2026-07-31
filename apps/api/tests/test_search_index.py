from __future__ import annotations

from datetime import date

from apps.api.tests.helpers import approve, ingest_text
from korpus.application.retrieval import HybridLexicalRetriever


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
