"""Shared read-through algorithm for baseline and explicit PEC cache modes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from korpus.application.corpus_read_context import ReadArguments, repository_read_scope
from korpus.domain.models import RetrievedEvidence


class QueryCache(Protocol):
    def get(self, key: str) -> tuple[RetrievedEvidence, ...] | None: ...
    def put(self, key: str, value: list[RetrievedEvidence]) -> None: ...


def read_cached(
    repository: object,
    cache: QueryCache,
    arguments: ReadArguments,
    key: Callable[[], str],
    action: Callable[[], list[RetrievedEvidence]],
) -> list[RetrievedEvidence]:
    with repository_read_scope(repository, arguments):
        selected = key()
        cached = cache.get(selected)
        if cached is not None:
            return list(cached)
        result = action()
        cache.put(selected, result)
        return result
