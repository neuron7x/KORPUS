"""Bind an ordinary retriever to one explicit corpus read token."""
from __future__ import annotations

from datetime import date

from korpus.application.corpus_snapshot import (
    CorpusReadToken,
    CorpusSnapshotReader,
    SnapshotRetriever,
)
from korpus.application.ports import Retriever
from korpus.domain.models import Identity, RetrievedEvidence


class SnapshotBoundRetriever(SnapshotRetriever):
    """Discard retrieval if the monotonic corpus state moves across the read."""

    def __init__(self, snapshot_reader: CorpusSnapshotReader, delegate: Retriever) -> None:
        self.snapshot_reader = snapshot_reader
        self.delegate = delegate

    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        token: CorpusReadToken,
        limit: int = 8,
    ) -> list[RetrievedEvidence]:
        self.snapshot_reader.validate(identity, corpus_ids, as_of, token)
        result = self.delegate.search(identity, text, corpus_ids, as_of, limit)
        self.snapshot_reader.validate(identity, corpus_ids, as_of, token)
        return result
