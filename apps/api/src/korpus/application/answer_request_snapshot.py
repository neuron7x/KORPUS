"""Per-request corpus token shared by cache and retrieval, with epoch guards."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from korpus.application.corpus_read_context import cache_release_token as cache_release_token
from korpus.application.corpus_read_context import repository_read_scope
from korpus.application.corpus_snapshot import (
    CorpusConsistencyError,
    CorpusReadToken,
    attached_snapshot_reader,
)
from korpus.application.pec_retrieval_types import SemanticControllableRetriever
from korpus.application.ports import Repository, Retriever
from korpus.domain.models import Identity, RetrievedEvidence


def token_is_stale(
    repository: Repository,
    identity: Identity,
    as_of: date,
    token: CorpusReadToken | None,
) -> bool:
    if token is None:
        return True
    try:
        validate_answer_token(repository, identity, token.corpus_ids, as_of, token)
    except CorpusConsistencyError:
        return True
    return False


def retrieval_failure_reason(error: Exception) -> str:
    return (
        "corpus_snapshot_changed"
        if isinstance(error, CorpusConsistencyError)
        else "retrieval_dependency_unavailable"
    )


def validate_answer_token(
    repository: Repository,
    identity: Identity,
    corpus_ids: frozenset[str],
    as_of: date,
    token: CorpusReadToken,
) -> None:
    reader = attached_snapshot_reader(repository)
    if reader is None:
        raise CorpusConsistencyError("corpus snapshot reader disappeared during answer")
    reader.validate(identity, corpus_ids, as_of, token)


class RequestBoundRetriever(Retriever):
    """Use the captured token for every retrieval variant, including cache hits."""

    def __init__(self, repository: Repository, delegate: Retriever, token: CorpusReadToken) -> None:
        self.repository = repository
        self.delegate = delegate
        self.token = token

    def _read(
        self,
        identity: Identity,
        corpora: frozenset[str],
        as_of: date,
        action: Callable[[], list[RetrievedEvidence]],
    ) -> list[RetrievedEvidence]:
        with repository_read_scope(self.repository, (identity, corpora, as_of), self.token):
            return action()

    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int = 8,
    ) -> list[RetrievedEvidence]:
        return self._read(
            identity,
            corpus_ids,
            as_of,
            lambda: self.delegate.search(identity, text, corpus_ids, as_of, limit),
        )

    def semantic_available(self) -> bool:
        return (
            isinstance(self.delegate, SemanticControllableRetriever)
            and self.delegate.semantic_available()
        )

    def search_with_semantic(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int = 8,
        *,
        semantic_enabled: bool,
    ) -> list[RetrievedEvidence]:
        def action() -> list[RetrievedEvidence]:
            delegate = self.delegate
            if isinstance(delegate, SemanticControllableRetriever):
                return delegate.search_with_semantic(
                    identity, text, corpus_ids, as_of, limit, semantic_enabled=semantic_enabled
                )
            return delegate.search(identity, text, corpus_ids, as_of, limit)

        return self._read(identity, corpus_ids, as_of, action)
