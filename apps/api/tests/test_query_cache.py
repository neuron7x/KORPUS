from datetime import date

import pytest
from korpus.application.cache import CachedRetriever, EvidenceQueryCache
from korpus.application.pec_cache import PECCachedRetriever
from korpus.domain.models import AccessTier, Identity

from apps.api.tests.helpers import StubSnapshotReader


class Repo:
    """Подвійник репозиторію мусить сказати, ЯКИЙ реліз він вдає, а не просто «r1»."""

    def __init__(self):
        self.corpus_snapshot_reader = StubSnapshotReader("a" * 64)

    @property
    def release(self):
        return self.corpus_snapshot_reader.release

    @release.setter
    def release(self, value):
        self.corpus_snapshot_reader.release = value


class Delegate:
    def __init__(self):
        self.calls = 0

    def search(self, identity, text, corpus_ids, as_of, limit=8):
        self.calls += 1
        return []


def identity(subject="a"):
    return Identity(
        subject=subject,
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
    )


def test_cache_is_bound_to_identity_release_and_configuration():
    repo = Repo()
    delegate = Delegate()
    cache = EvidenceQueryCache(maximum_entries=8, ttl_seconds=60)
    retriever = CachedRetriever(repo, delegate, cache, "config-a")
    for _ in range(2):
        retriever.search(identity("alice"), "query", frozenset({"public"}), date(2026, 1, 1))
    assert delegate.calls == 1
    retriever.search(identity("bob"), "query", frozenset({"public"}), date(2026, 1, 1))
    assert delegate.calls == 2
    repo.release = "b" * 64
    retriever.search(identity("alice"), "query", frozenset({"public"}), date(2026, 1, 1))
    assert delegate.calls == 3
    assert cache.stats().hits == 1


@pytest.mark.parametrize(
    ("retriever_type", "semantic_enabled"),
    [
        (CachedRetriever, None),
        (PECCachedRetriever, None),
        (PECCachedRetriever, False),
        (PECCachedRetriever, True),
    ],
    ids=("baseline", "pec-default", "pec-lexical", "pec-semantic"),
)
def test_shared_cache_recomputes_only_for_a_different_configuration(
    retriever_type, semantic_enabled
):
    """One corpus state must not share cached evidence across ranking contracts."""

    class ModeDelegate(Delegate):
        def search_with_semantic(
            self, identity, text, corpus_ids, as_of, limit=8, *, semantic_enabled
        ):
            return self.search(identity, text, corpus_ids, as_of, limit)

    repo = Repo()
    delegate = ModeDelegate()
    cache = EvidenceQueryCache(maximum_entries=8, ttl_seconds=60)
    first = retriever_type(repo, delegate, cache, "same-profile:obligations-v1")
    changed = retriever_type(repo, delegate, cache, "same-profile:obligations-v2")
    same = retriever_type(repo, delegate, cache, "same-profile:obligations-v1")

    def search(retriever):
        arguments = (identity("alice"), "archive card", frozenset({"public"}), date(2026, 1, 1))
        if semantic_enabled is None:
            return retriever.search(*arguments)
        return retriever.search_with_semantic(*arguments, semantic_enabled=semantic_enabled)

    assert search(first) == []
    assert delegate.calls == 1
    assert search(changed) == []
    assert delegate.calls == 2
    assert search(same) == []
    assert search(changed) == []
    assert delegate.calls == 2
    assert cache.stats().hits == 2
    assert cache.stats().misses == 2


def test_cache_is_bounded_lru():
    cache = EvidenceQueryCache(maximum_entries=2, ttl_seconds=60)
    cache.put("a", [])
    cache.put("b", [])
    cache.put("c", [])
    assert cache.get("a") is None
    assert cache.stats().evictions == 1


def test_two_compartment_sets_do_not_share_a_cached_result() -> None:
    """Compartments decide which spans retrieval returns; the key ignored them.

    `retrieval_queries.compartment_predicate` filters spans by
    `identity.compartments`, and entitlements are resolved per request from the
    profile — so one subject's compartments change between requests. Until 2026-08-06
    the cache key carried subject, clearance, roles and corpora but not compartments,
    which meant that for the length of the TTL a reader kept being served evidence a
    withdrawn compartment had granted. Revocation latency in a design that is
    fail-closed everywhere else.
    """
    from datetime import date

    from korpus.application.cache import CachedRetriever
    from korpus.domain.models import AccessTier, Identity

    class ReleaseOnly:
        corpus_snapshot_reader = StubSnapshotReader("c" * 64)

    def identity(compartments: set[str]) -> Identity:
        return Identity(
            subject="same-subject",
            roles=frozenset({"user"}),
            clearance=AccessTier.RESTRICTED,
            corpora=frozenset({"public"}),
            compartments=frozenset(compartments),
        )

    retriever = CachedRetriever.__new__(CachedRetriever)
    retriever.repository = ReleaseOnly()
    retriever.configuration_id = "configuration"

    arguments = ("яка дистанція", frozenset({"public"}), date(2026, 8, 6), 8)
    entitled = retriever._key(identity({"alpha", "bravo"}), *arguments)
    withdrawn = retriever._key(identity(set()), *arguments)
    narrowed = retriever._key(identity({"alpha"}), *arguments)

    assert entitled != withdrawn
    assert entitled != narrowed
    # The dual: identical compartments must still hit, or the cache is disabled rather
    # than corrected.
    assert entitled == retriever._key(identity({"bravo", "alpha"}), *arguments)


def test_semantic_cache_does_not_alias_distinct_raw_queries() -> None:
    from korpus.application.pec_cache import PECCachedRetriever

    class RawSemanticDelegate:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def search(self, identity, text, corpus_ids, as_of, limit=8):
            self.calls.append(("default", text))
            return []

        def search_with_semantic(
            self, identity, text, corpus_ids, as_of, limit=8, *, semantic_enabled
        ):
            self.calls.append(("semantic" if semantic_enabled else "lexical", text))
            return []

    aliases = (
        ("US policy", "us policy"),
        ("Права СУБ'ЄКТА", "Права суб'єкта"),
        ("court’s holding", "court's holding"),
    )
    for first, second in aliases:
        for mode in ("default", "semantic"):
            delegate = RawSemanticDelegate()
            retriever = PECCachedRetriever(
                Repo(),
                delegate,
                EvidenceQueryCache(maximum_entries=8, ttl_seconds=60),
                "semantic-config",
            )
            for query in (first, second, first):
                if mode == "default":
                    assert (
                        retriever.search(
                            identity(), query, frozenset({"public"}), date(2026, 11, 6)
                        )
                        == []
                    )
                else:
                    assert (
                        retriever.search_with_semantic(
                            identity(),
                            query,
                            frozenset({"public"}),
                            date(2026, 11, 6),
                            semantic_enabled=True,
                        )
                        == []
                    )
            assert delegate.calls == [(mode, first), (mode, second)]
