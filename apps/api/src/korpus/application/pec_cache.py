from __future__ import annotations

import hashlib
from datetime import date

from korpus.application.cache import CachedRetriever
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
        return hashlib.sha256(f"{baseline}\x1f{mode}".encode("utf-8")).hexdigest()

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
        key = self._mode_key(identity, text, corpus_ids, as_of, limit, semantic_enabled)
        cached = self.cache.get(key)
        if cached is not None:
            return list(cached)
        result = method(
            identity,
            text,
            corpus_ids,
            as_of,
            limit,
            semantic_enabled=semantic_enabled,
        )
        self.cache.put(key, result)
        return result
