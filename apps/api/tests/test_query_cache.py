from datetime import date

import pytest

from korpus.application.cache import CachedRetriever, EvidenceQueryCache
from korpus.application.corpus_snapshot import (
    CorpusConsistencyError,
    CorpusReadToken,
    authorization_scope_id,
)
from korpus.domain.models import AccessTier, Identity


class SnapshotReader:
    def __init__(self) -> None:
        self.epoch = 1
        self.release = "1" * 64

    def capture(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
    ) -> CorpusReadToken:
        authorized = frozenset(corpus_ids.intersection(identity.corpora))
        return CorpusReadToken(
            state_epoch=self.epoch,
            release_id=self.release,
            as_of=as_of,
            corpus_ids=authorized,
            authorization_scope_id=authorization_scope_id(identity, authorized),
        )

    def validate(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
        token: CorpusReadToken,
    ) -> None:
        current = self.capture(identity, corpus_ids, as_of)
        if current != token:
            raise CorpusConsistencyError("test corpus moved")


class Delegate:
    def __init__(self) -> None:
        self.calls = 0

    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        token: CorpusReadToken,
        limit: int = 8,
    ) -> list:
        self.calls += 1
        return []


def identity(subject: str = "a", compartments: set[str] | None = None) -> Identity:
    return Identity(
        subject=subject,
        roles=frozenset({"user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
        compartments=frozenset(compartments or set()),
    )


def test_cached_retriever_rejects_split_snapshot_authorities() -> None:
    reader = SnapshotReader()
    other_reader = SnapshotReader()
    delegate = Delegate()
    delegate.snapshot_reader = other_reader  # type: ignore[attr-defined]
    cache = EvidenceQueryCache(maximum_entries=8, ttl_seconds=60)

    with pytest.raises(ValueError, match="share one corpus snapshot reader"):
        CachedRetriever(reader, delegate, cache, "config-a")  # type: ignore[arg-type]


def test_cache_is_bound_to_identity_release_epoch_and_configuration() -> None:
    reader = SnapshotReader()
    delegate = Delegate()
    cache = EvidenceQueryCache(maximum_entries=8, ttl_seconds=60)
    retriever = CachedRetriever(reader, delegate, cache, "config-a")
    as_of = date(2026, 1, 1)
    corpora = frozenset({"public"})

    alice = identity("alice")
    alice_token = reader.capture(alice, corpora, as_of)
    for _ in range(2):
        retriever.search(alice, "query", corpora, as_of, alice_token)
    assert delegate.calls == 1

    bob = identity("bob")
    retriever.search(bob, "query", corpora, as_of, reader.capture(bob, corpora, as_of))
    assert delegate.calls == 2

    # The content identity can return to the same value while the live state cannot.
    # A cache key that omits the monotonic epoch would incorrectly reuse Alice's first hit.
    reader.epoch = 2
    retriever.search(alice, "query", corpora, as_of, reader.capture(alice, corpora, as_of))
    assert delegate.calls == 3

    reader.epoch = 3
    reader.release = "2" * 64
    retriever.search(alice, "query", corpora, as_of, reader.capture(alice, corpora, as_of))
    assert delegate.calls == 4
    assert cache.stats().hits == 1


def test_cache_key_commits_release_even_if_epoch_source_misses_a_change() -> None:
    reader = SnapshotReader()
    delegate = Delegate()
    cache = EvidenceQueryCache(maximum_entries=8, ttl_seconds=60)
    retriever = CachedRetriever(reader, delegate, cache, "config-a")
    actor = identity("alice")
    corpora = frozenset({"public"})
    as_of = date(2026, 1, 1)

    token_a = reader.capture(actor, corpora, as_of)
    retriever.search(actor, "query", corpora, as_of, token_a)
    assert delegate.calls == 1

    reader.release = "2" * 64
    token_b = reader.capture(actor, corpora, as_of)
    assert token_b.state_epoch == token_a.state_epoch
    retriever.search(actor, "query", corpora, as_of, token_b)
    assert delegate.calls == 2


def test_cache_never_returns_hit_if_state_changes_during_lookup() -> None:
    reader = SnapshotReader()

    class MutatingCache(EvidenceQueryCache):
        mutate = False

        def get(self, key: str):
            value = super().get(key)
            if self.mutate and value is not None:
                reader.epoch += 1
            return value

    delegate = Delegate()
    cache = MutatingCache(maximum_entries=8, ttl_seconds=60)
    retriever = CachedRetriever(reader, delegate, cache, "config-a")
    actor = identity("alice")
    corpora = frozenset({"public"})
    as_of = date(2026, 1, 1)
    token = reader.capture(actor, corpora, as_of)

    retriever.search(actor, "query", corpora, as_of, token)
    assert delegate.calls == 1
    cache.mutate = True

    with pytest.raises(CorpusConsistencyError):
        retriever.search(actor, "query", corpora, as_of, token)
    assert delegate.calls == 1


def test_cache_never_stores_result_if_state_changes_during_search() -> None:
    """Deterministic destruction control C for issue #23, without scheduler timing."""
    reader = SnapshotReader()

    class MutatingDelegate(Delegate):
        def search(
            self,
            identity: Identity,
            text: str,
            corpus_ids: frozenset[str],
            as_of: date,
            token: CorpusReadToken,
            limit: int = 8,
        ) -> list:
            self.calls += 1
            if self.calls == 1:
                reader.epoch = 2
                reader.release = "2" * 64
            return []

    delegate = MutatingDelegate()
    cache = EvidenceQueryCache(maximum_entries=8, ttl_seconds=60)
    retriever = CachedRetriever(reader, delegate, cache, "config-a")
    actor = identity("alice")
    corpora = frozenset({"public"})
    as_of = date(2026, 1, 1)
    token_a = reader.capture(actor, corpora, as_of)

    with pytest.raises(CorpusConsistencyError):
        retriever.search(actor, "query", corpora, as_of, token_a)
    assert cache.stats().entries == 0

    # Logical A returns, but the monotonic epoch does not: A→B→A is not the old A.
    reader.epoch = 3
    reader.release = "1" * 64
    token_aba = reader.capture(actor, corpora, as_of)
    retriever.search(actor, "query", corpora, as_of, token_aba)
    assert delegate.calls == 2


def test_cache_is_bounded_lru() -> None:
    cache = EvidenceQueryCache(maximum_entries=2, ttl_seconds=60)
    cache.put("a", [])
    cache.put("b", [])
    cache.put("c", [])
    assert cache.get("a") is None
    assert cache.stats().evictions == 1


def test_two_compartment_sets_do_not_share_a_cached_result() -> None:
    reader = SnapshotReader()
    retriever = CachedRetriever.__new__(CachedRetriever)
    retriever.configuration_id = "configuration"
    as_of = date(2026, 8, 6)
    corpora = frozenset({"public"})

    def key(compartments: set[str]) -> str:
        actor = identity("same-subject", compartments)
        token = reader.capture(actor, corpora, as_of)
        return retriever._key(actor, "яка дистанція", corpora, as_of, token, 8)

    entitled = key({"alpha", "bravo"})
    withdrawn = key(set())
    narrowed = key({"alpha"})

    assert entitled != withdrawn
    assert entitled != narrowed
    assert entitled == key({"bravo", "alpha"})
