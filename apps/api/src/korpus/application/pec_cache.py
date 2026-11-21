from __future__ import annotations

import hashlib
from datetime import date
from functools import partial

from korpus.application.cache import CachedRetriever
from korpus.application.query_cache_read import read_cached
from korpus.domain.models import Identity, RetrievedEvidence


class PECCachedRetriever(CachedRetriever):
    """Mode-aware cache adapter without changing the baseline cache contract."""

    def semantic_available(self) -> bool:
        method = getattr(self.delegate, "semantic_available", None)
        return bool(method()) if callable(method) else False

    def _mode_key(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int,
        semantic_enabled: bool,
    ) -> str:
        baseline = self._key(identity, text, corpus_ids, as_of, limit)
        mode = "semantic" if semantic_enabled else "lexical"
        return hashlib.sha256(f"{baseline}\x1f{mode}".encode()).hexdigest()

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
        method = getattr(self.delegate, "search_with_semantic", None)
        if not callable(method):
            return self.search(identity, text, corpus_ids, as_of, limit)
        arguments = (identity, text, corpus_ids, as_of, limit)
        return read_cached(
            self.repository,
            self.cache,
            (identity, corpus_ids, as_of),
            partial(self._mode_key, *arguments, semantic_enabled),
            partial(method, *arguments, semantic_enabled=semantic_enabled),
        )
