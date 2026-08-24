from __future__ import annotations

from datetime import date

from apps.api.tests.helpers import approve, ingest_text


def test_public_candidate_scores_are_unchanged_by_restricted_corpus(
    client, admin_identity, public_identity
):
    public = ingest_text(
        client,
        title="Public reference",
        text="Кожен запис журналу має містити дату та відповідальну особу.",
    )
    approve(client, public["version"]["id"])
    from korpus.application.retrieval import HybridLexicalRetriever

    repository = client.app.state.repository
    retriever = HybridLexicalRetriever(repository)
    before = retriever.search(
        public_identity, "дата відповідальна особа", frozenset({"public"}), date.today()
    )

    restricted = ingest_text(
        client,
        title="Restricted noise",
        corpus_id="restricted-demo",
        access_tier=3,
        text="дата відповідальна особа " * 200 + "SECRET-SIDE-CHANNEL",
    )
    approve(client, restricted["version"]["id"])
    after = retriever.search(
        public_identity, "дата відповідальна особа", frozenset({"public"}), date.today()
    )

    before_projection = [(item.span.id, item.score, item.rank) for item in before]
    after_projection = [(item.span.id, item.score, item.rank) for item in after]
    assert before_projection == after_projection
