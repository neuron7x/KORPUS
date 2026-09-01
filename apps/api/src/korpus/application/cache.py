from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date

from korpus.application.corpus_snapshot import release_token
from korpus.application.ports import Repository, Retriever
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


class CachedRetriever(Retriever):
    def __init__(
        self,
        repository: Repository,
        delegate: Retriever,
        cache: EvidenceQueryCache,
        configuration_id: str,
    ) -> None:
        self.repository = repository
        self.delegate = delegate
        self.cache = cache
        self.configuration_id = configuration_id

    def _key(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int,
    ) -> str:
        # Ключ мусить нести ТУ САМУ релізну тотожність, яку відповідь назве читачеві.
        # Поки їх було дві, кеш умів віддати відповідь, засвідчену іншим релізом, ніж
        # той, за яким її поклали, — і жодне поле не розрізняло ці два випадки.
        release_id = release_token(self.repository, identity, corpus_ids, as_of).release_id
        material = "\x1f".join(
            [
                identity.subject,
                str(int(identity.clearance)),
                ",".join(sorted(identity.roles)),
                ",".join(sorted(identity.corpora)),
                # Compartments decide which spans the retrieval projection returns
                # (`retrieval_queries.compartment_predicate`) and were missing from this
                # key until 2026-08-06. Entitlements are resolved per request from the
                # profile, so one subject's compartments change between requests — and
                # for the length of the TTL the cache kept serving evidence the
                # withdrawn compartment had granted. Revocation latency in a system
                # whose whole design is fail-closed.
                ",".join(sorted(identity.compartments)),
                ",".join(sorted(corpus_ids)),
                as_of.isoformat(),
                str(limit),
                self.configuration_id,
                release_id,
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
        limit: int = 8,
    ) -> list[RetrievedEvidence]:
        key = self._key(identity, text, corpus_ids, as_of, limit)
        cached = self.cache.get(key)
        if cached is not None:
            return list(cached)
        result = self.delegate.search(identity, text, corpus_ids, as_of, limit)
        self.cache.put(key, result)
        return result
