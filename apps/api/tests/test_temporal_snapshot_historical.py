from __future__ import annotations

from datetime import date

import pytest

from apps.api.tests.helpers import approve, ingest_text
from korpus.application.corpus_snapshot import CorpusConsistencyError
from korpus.application.retrieval import HybridLexicalRetriever
from korpus.application.snapshot_retrieval import SnapshotBoundRetriever


def test_historical_as_of_is_bound_to_release_and_retrieval(client, admin_identity) -> None:
    result = ingest_text(
        client,
        title="Historical temporal fixture",
        text="Маркер HISTORICAL-SNAPSHOT був чинним лише у визначеному інтервалі.",
        effective_from=date(2020, 1, 1),
        effective_until=date(2022, 12, 31),
    )
    version = result["version"]
    assert isinstance(version, dict)
    version_id = str(version["id"])
    approve(client, version_id)

    repository = client.app.state.repository
    reader = client.app.state.corpus_snapshot_reader
    corpora = frozenset({"public"})
    historical = date(2021, 6, 1)
    expired = date(2024, 6, 1)

    historical_token = reader.capture(admin_identity, corpora, historical)
    expired_token = reader.capture(admin_identity, corpora, expired)
    assert historical_token.state_epoch == expired_token.state_epoch
    assert historical_token.release_id != expired_token.release_id

    retriever = SnapshotBoundRetriever(
        reader,
        HybridLexicalRetriever(repository, candidate_budget=8),
    )
    evidence = retriever.search(
        admin_identity,
        "HISTORICAL-SNAPSHOT визначеному інтервалі",
        corpora,
        historical,
        historical_token,
    )
    assert evidence
    assert any(str(item.version.id) == version_id for item in evidence)

    assert (
        retriever.search(
            admin_identity,
            "HISTORICAL-SNAPSHOT визначеному інтервалі",
            corpora,
            expired,
            expired_token,
        )
        == []
    )

    with pytest.raises(CorpusConsistencyError):
        retriever.search(
            admin_identity,
            "HISTORICAL-SNAPSHOT визначеному інтервалі",
            corpora,
            expired,
            historical_token,
        )
