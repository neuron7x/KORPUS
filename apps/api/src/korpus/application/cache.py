from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date

from korpus.application.corpus_snapshot import (
    CorpusReadToken,
    CorpusSnapshotReader,
    SnapshotRetriever,
)
from korpus.application.retrieval import normalize_text
from korpus.domain.models import Identity, RetrievedEvidence


@dataclass(frozen=True)
class CacheStats:
    hits: int
    misses: int
    evictions: int
    entries: int


@dataclass(frozen=True)
class _Entry:
    expires_at: float
    value: tuple[RetrievedEvidence, ...]


class EvidenceQueryCache:
    """Identity- and release-bound bounded LRU cache.

    The cache cannot survive a corpus release change, permission change, date
    change, or ranking configuration change. It stores already authorized
    evidence only and never broadens a caller's scope.
    """

    def __init__(self, maximum_entries: int = 512, ttl_seconds: float = 30.0) -> None:
        if maximum_entries < 1 or ttl_seconds <= 0:
            raise ValueError("cache limits must be positive")
        self.maximum_entries = maximum_entries
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str) -> tuple[RetrievedEvidence, ...] | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.expires_at <= now:
                if entry is not None:
                    self._entries.pop(key, None)
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return entry.value

    def put(self, key: str, value: list[RetrievedEvidence]) -> None:
        with self._lock:
            self._entries[key] = _Entry(time.monotonic() + self.ttl_seconds, tuple(value))
            self._entries.move_to_end(key)
            while len(self._entries) > self.maximum_entries:
                self._entries.popitem(last=False)
                self._evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(self._hits, self._misses, self._evictions, len(self._entries))


class CachedRetriever(SnapshotRetriever):
    """Cache only evidence that was read under the caller's explicit snapshot token."""

    def __init__(
        self,
        snapshot_reader: CorpusSnapshotReader,
        delegate: SnapshotRetriever,
        cache: EvidenceQueryCache,
        configuration_id: str,
    ) -> None:
        self.snapshot_reader = snapshot_reader
        self.delegate = delegate
        self.cache = cache
        self.configuration_id = configuration_id

    def _key(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        token: CorpusReadToken,
        limit: int,
    ) -> str:
        material = "\x1f".join(
            [
                identity.subject,
                token.authorization_scope_id,
                ",".join(sorted(token.corpus_ids)),
                as_of.isoformat(),
                str(limit),
                self.configuration_id,
                str(token.state_epoch),
                token.release_id,
                normalize_text(text),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        token: CorpusReadToken,
        limit: int = 8,
    ) -> list[RetrievedEvidence]:
        # The cache must never discover release identity for itself. That creates a
        # second read point and can key state-B evidence as release A. One token from the
        # answer path is the only authority for both the lookup and any subsequent put.
        self.snapshot_reader.validate(identity, corpus_ids, as_of, token)
        key = self._key(identity, text, corpus_ids, as_of, token, limit)
        cached = self.cache.get(key)
        if cached is not None:
            self.snapshot_reader.validate(identity, corpus_ids, as_of, token)
            return list(cached)
        result = self.delegate.search(identity, text, corpus_ids, as_of, token, limit)
        self.snapshot_reader.validate(identity, corpus_ids, as_of, token)
        self.cache.put(key, result)
        return result
