import hashlib
from datetime import date

from korpus.application.cache import CachedRetriever, EvidenceQueryCache
from korpus.domain.models import AccessTier, Identity

from apps.api.tests.helpers import approve, ingest_text


class Repo:
    def __init__(self):
        self.release = "r1"

    def corpus_release_id(self, identity, corpus_ids, as_of):
        return self.release


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
    repo.release = "r2"
    retriever.search(identity("alice"), "query", frozenset({"public"}), date(2026, 1, 1))
    assert delegate.calls == 3
    assert cache.stats().hits == 1


def test_cache_is_bounded_lru():
    cache = EvidenceQueryCache(maximum_entries=2, ttl_seconds=60)
    cache.put("a", [])
    cache.put("b", [])
    cache.put("c", [])
    assert cache.get("a") is None
    assert cache.stats().evictions == 1


def test_release_fingerprint_does_not_materialize_spans(client, monkeypatch):
    result = ingest_text(client, text="RELEASE-MARKER approved evidence.")
    approve(client, result["version"]["id"])
    repository = client.app.state.repository
    retrievable = repository.list_retrievable_spans(
        client.identity_provider.current,
        frozenset({"public"}),
        date.today(),
    )
    legacy_rows = {
        (str(document.id), str(version.id), version.source_hash, version.review_state.value)
        for _, document, version in retrievable
    }
    expected = hashlib.sha256()
    for row in sorted(legacy_rows):
        expected.update(":".join(row).encode("utf-8") + b"\n")

    def forbidden_materialization(*args, **kwargs):
        raise AssertionError("release fingerprint materialized evidence spans")

    monkeypatch.setattr(repository, "_materialize_current", forbidden_materialization)
    release = repository.corpus_release_id(
        client.identity_provider.current,
        frozenset({"public"}),
        date.today(),
    )
    assert release == expected.hexdigest()[:16]
