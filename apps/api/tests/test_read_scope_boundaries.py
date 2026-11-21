"""Neutral protocol controls observe storage/scoring before an outer refusal."""

from __future__ import annotations

from collections import OrderedDict
from datetime import date
from functools import partial

import pytest
from korpus.application import retrieval_hybrid
from korpus.application.answer_request_snapshot import RequestBoundRetriever, cache_release_token
from korpus.application.cache import CachedRetriever, EvidenceQueryCache
from korpus.application.corpus_snapshot import CorpusConsistencyError
from korpus.application.pec_cache import PECCachedRetriever
from korpus.application.retrieval import HybridLexicalRetriever, RetrievalWeights
from korpus.application.snapshot_retrieval import SnapshotBoundRetriever
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    ReviewState,
)

from .test_answer_request_snapshot_gate import _fixture

MODES = ("baseline", "pec-default", "pec-lexical", "pec-semantic")
ENTRIES = ("standalone", "request-bound", "snapshot-bound")


class ObservedEntries(OrderedDict):
    def __init__(self):
        super().__init__()
        self.insertions = []

    def __setitem__(self, key, value):
        self.insertions.append((key, value))
        return super().__setitem__(key, value)


class ModeDelegate:
    def __init__(self, action):
        self.action = action
        self.calls = 0

    def search(self, *_args, **_kwargs):
        self.calls += 1
        return self.action()

    def search_with_semantic(self, *args, semantic_enabled, **kwargs):
        return self.search(*args, **kwargs)


def cached_call(fixture, delegate, mode, entry):
    reader, repository, identity, corpora, as_of, token = fixture
    cache = EvidenceQueryCache()
    cache._entries = ObservedEntries()
    kind = CachedRetriever if mode == "baseline" else PECCachedRetriever
    cached = kind(repository, delegate, cache, "neutral-snapshot-boundary")

    class FixedMode:
        def search(self, *args):
            if mode in {"baseline", "pec-default"}:
                return cached.search(*args)
            return cached.search_with_semantic(*args, semantic_enabled=mode == "pec-semantic")

    adapter = FixedMode()
    if entry == "standalone":
        search = partial(adapter.search, identity, "archive card", corpora, as_of)
    elif entry == "request-bound":
        bound = RequestBoundRetriever(repository, adapter, token)
        search = partial(bound.search, identity, "archive card", corpora, as_of)
    else:
        bound = SnapshotBoundRetriever(reader, adapter)
        search = partial(bound.search, identity, "archive card", corpora, as_of, token)
    return cache, search


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("mode", MODES)
def test_changed_delegate_result_never_reaches_cache_storage(mode, entry) -> None:
    fixture = _fixture()
    reader, repository, identity, corpora, as_of, _token = fixture

    def changed_result():
        reader.epoch += 1
        reader.release = "b" * 64
        return ["neutral-result-from-B"]

    delegate = ModeDelegate(changed_result)
    cache, search = cached_call(fixture, delegate, mode, entry)
    with pytest.raises(CorpusConsistencyError):
        search()
    assert delegate.calls == 1
    assert cache._entries.insertions == [], "an intermediate write cannot be repaired by clearing"
    assert cache.stats().entries == 0
    before = reader.captures
    after = cache_release_token(repository, identity, corpora, as_of)
    assert after.state_epoch == 8 and reader.captures == before + 1


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("mode", MODES)
def test_stable_snapshot_preserves_real_cache_hit_and_single_capture(mode, entry) -> None:
    fixture = _fixture()
    reader = fixture[0]
    delegate = ModeDelegate(lambda: ["neutral-result-from-A"])
    cache, search = cached_call(fixture, delegate, mode, entry)
    before = reader.captures
    for _ in range(2):
        assert search() == ["neutral-result-from-A"]
    assert delegate.calls == 1
    assert cache.stats().misses == cache.stats().hits == 1
    assert len(cache._entries.insertions) == 1
    assert reader.captures - before == (2 if entry == "standalone" else 0)


def candidate(label):
    document = DocumentRecord(
        canonical_title="Archive " + label,
        corpus_id="public",
        issuer="Neutral test authority",
        jurisdiction="ZZ",
        document_type="record",
        access_tier=AccessTier.PUBLIC,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1",
        source_hash="a" * 64,
        object_key="neutral/" + label,
        mime_type="text/plain",
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.APPROVED,
        publication_date=date(2020, 1, 1),
    )
    span = EvidenceSpanRecord(
        version_id=version.id, ordinal=0, text="archive card neutral evidence " + label
    )
    return span, document, version


@pytest.mark.parametrize("entry", (*ENTRIES, "request-direct", "snapshot-direct"))
@pytest.mark.parametrize("changed", (False, True), ids=("stable", "changed"))
def test_complete_semantic_backfill_is_validated_before_actual_scoring(
    monkeypatch, entry, changed
) -> None:
    fixture = _fixture()
    reader, repository, _identity, _corpora, _as_of, _token = fixture
    first, second = candidate("A"), candidate("B")
    repository.search_retrievable_spans = lambda *_args: [first]
    backfills = []

    def backfill(_identity, _corpora, _as_of, identifiers):
        backfills.append(tuple(identifiers))
        return [second]

    repository.get_retrievable_spans_by_ids = backfill

    class Semantic:
        def search(self, *_args):
            if changed:
                reader.epoch += 1
                reader.release = "b" * 64
            return [(second[0].id, 0.9)]

    original = retrieval_hybrid.score_candidates
    observed = []

    def score(*args, **kwargs):
        observed.append(list(args[1]))
        return original(*args, **kwargs)

    monkeypatch.setattr(retrieval_hybrid, "score_candidates", score)
    delegate = HybridLexicalRetriever(
        repository,
        candidate_budget=8,
        semantic_source=Semantic(),
        weights=RetrievalWeights(
            lexical=0.32,
            semantic=0.10,
            query_coverage=0.24,
            character=0.10,
            authority=0.14,
            phrase=0.06,
            temporal=0.04,
        ),
    )
    cache = None
    if entry == "request-direct":
        bound = RequestBoundRetriever(repository, delegate, _token)
        search = partial(bound.search, _identity, "archive card", _corpora, _as_of)
    elif entry == "snapshot-direct":
        bound = SnapshotBoundRetriever(reader, delegate)
        search = partial(bound.search, _identity, "archive card", _corpora, _as_of, _token)
    else:
        cache, search = cached_call(fixture, delegate, "pec-semantic", entry)
    if changed:
        with pytest.raises(CorpusConsistencyError):
            search()
        assert observed == [], "mixed candidates reached the real ranking function"
        if cache is not None:
            assert cache._entries.insertions == []
    else:
        result = search()
        assert {item.span.id for item in result} == {first[0].id, second[0].id}
        assert observed == [[first[0].text, second[0].text]]
    assert backfills == [(second[0].id,)]


@pytest.mark.parametrize("shared_reader", (False, True))
def test_other_repository_cannot_borrow_an_active_token(shared_reader) -> None:
    first, second = _fixture(), _fixture()
    reader, repository, identity, corpora, as_of, token = first
    foreign = second[1]
    if shared_reader:
        foreign.corpus_snapshot_reader = reader
    delegate = ModeDelegate(lambda: ["foreign-repository"])
    cached = CachedRetriever(foreign, delegate, EvidenceQueryCache(), "same-shaped-token")
    bound = RequestBoundRetriever(repository, cached, token)
    with pytest.raises(CorpusConsistencyError, match="authority"):
        bound.search(identity, "archive card", corpora, as_of)
    assert delegate.calls == 0


def test_nested_failed_read_restores_the_exact_outer_scope_then_removes_it() -> None:
    outer, inner = _fixture(), _fixture()
    reader, repository, identity, corpora, as_of, token = outer
    nested_reader, nested_repository, *_ = inner

    def nested_change():
        nested_reader.epoch += 1
        return []

    nested = RequestBoundRetriever(nested_repository, ModeDelegate(nested_change), inner[-1])

    def outer_action():
        assert cache_release_token(repository, identity, corpora, as_of) is token
        with pytest.raises(CorpusConsistencyError):
            nested.search(identity, "nested archive", corpora, as_of)
        assert cache_release_token(repository, identity, corpora, as_of) is token
        return []

    assert (
        RequestBoundRetriever(repository, ModeDelegate(outer_action), token).search(
            identity, "outer archive", corpora, as_of
        )
        == []
    )
    assert reader.captures == nested_reader.captures == 1
    assert cache_release_token(repository, identity, corpora, as_of) == token
    assert reader.captures == 2


def test_reader_replacement_after_key_capture_refuses_before_storage() -> None:
    fixture, replacement = _fixture(), _fixture()
    repository = fixture[1]

    def replace_reader():
        repository.corpus_snapshot_reader = replacement[0]
        return ["same-shaped-foreign-authority"]

    cache, search = cached_call(fixture, ModeDelegate(replace_reader), "baseline", "request-bound")
    with pytest.raises(CorpusConsistencyError, match="authority"):
        search()
    assert cache._entries.insertions == []
