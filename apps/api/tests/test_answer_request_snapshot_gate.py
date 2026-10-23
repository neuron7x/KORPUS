"""Deterministic release/cached-retrieval interleaving controls for issue #23."""

from __future__ import annotations

from datetime import date

import pytest
from korpus.application.answer_request_snapshot import (
    RequestBoundRetriever,
    cache_release_token,
)
from korpus.application.cache import CachedRetriever, EvidenceQueryCache
from korpus.application.corpus_snapshot import (
    CorpusConsistencyError,
    CorpusReadToken,
    authorization_scope_id,
)
from korpus.domain.models import AccessTier, Identity


class _SnapshotReader:
    def __init__(self) -> None:
        self.epoch = 7
        self.release = "a" * 64
        self.captures = 0
        self.validations = 0

    def capture(self, identity, corpus_ids, as_of):
        self.captures += 1
        authorized = frozenset(corpus_ids.intersection(identity.corpora))
        return CorpusReadToken(
            state_epoch=self.epoch,
            release_id=self.release,
            as_of=as_of,
            corpus_ids=authorized,
            authorization_scope_id=authorization_scope_id(identity, authorized),
        )

    def validate(self, identity, corpus_ids, as_of, token):
        self.validations += 1
        expected = self.capture_without_increment(identity, corpus_ids, as_of)
        if expected != token:
            raise CorpusConsistencyError("epoch/scope/release changed")

    def capture_without_increment(self, identity, corpus_ids, as_of):
        authorized = frozenset(corpus_ids.intersection(identity.corpora))
        return CorpusReadToken(
            state_epoch=self.epoch,
            release_id=self.release,
            as_of=as_of,
            corpus_ids=authorized,
            authorization_scope_id=authorization_scope_id(identity, authorized),
        )


class _Repo:
    def __init__(self, reader: _SnapshotReader):
        self.corpus_snapshot_reader = reader


class _Delegate:
    def __init__(self, mutate=None):
        self.calls = 0
        self.mutate = mutate

    def search(self, identity, text, corpus_ids, as_of, limit=8):
        self.calls += 1
        if self.mutate is not None:
            self.mutate()
        return []


def _identity(compartments=frozenset()) -> Identity:
    return Identity(
        subject="snapshot-reader",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
        compartments=frozenset(compartments),
    )


def _fixture():
    reader = _SnapshotReader()
    repo = _Repo(reader)
    identity = _identity()
    corpora = frozenset({"public"})
    as_of = date(2026, 10, 23)
    token = reader.capture(identity, corpora, as_of)
    return reader, repo, identity, corpora, as_of, token


def test_cache_reuses_answer_token_instead_of_recapturing_release() -> None:
    reader, repo, identity, corpora, as_of, token = _fixture()
    delegate = _Delegate()
    cached = CachedRetriever(repo, delegate, EvidenceQueryCache(), "test-config")  # type: ignore[arg-type]
    bound = RequestBoundRetriever(repo, cached, token)  # type: ignore[arg-type]
    for _ in range(2):
        assert bound.search(identity, "контрольний запит", corpora, as_of) == []
    assert delegate.calls == 1
    assert reader.captures == 1
    assert reader.validations == 4


def test_approval_after_capture_cannot_return_new_corpus_evidence() -> None:
    reader, repo, identity, corpora, as_of, token = _fixture()

    def approve_new_version():
        reader.epoch += 1
        reader.release = "b" * 64

    delegate = _Delegate(approve_new_version)
    bound = RequestBoundRetriever(repo, delegate, token)  # type: ignore[arg-type]
    with pytest.raises(CorpusConsistencyError):
        bound.search(identity, "newly approved", corpora, as_of)
    assert delegate.calls == 1


def test_epoch_refuses_aba_even_when_release_digest_returns_to_a() -> None:
    reader, repo, identity, corpora, as_of, token = _fixture()

    def change_and_revert():
        reader.epoch += 2
        reader.release = "a" * 64

    bound = RequestBoundRetriever(repo, _Delegate(change_and_revert), token)  # type: ignore[arg-type]
    with pytest.raises(CorpusConsistencyError):
        bound.search(identity, "ABA", corpora, as_of)


def test_cache_snapshot_scope_cannot_be_relabelled() -> None:
    _reader, repo, identity, corpora, as_of, token = _fixture()
    delegate = _Delegate()
    bound = RequestBoundRetriever(repo, delegate, token)  # type: ignore[arg-type]
    with pytest.raises(CorpusConsistencyError):
        bound.search(identity, "as_of mismatch", corpora, date(2026, 10, 22))
    with pytest.raises(CorpusConsistencyError):
        bound.search(_identity({"new-compartment"}), "scope mismatch", corpora, as_of)
    assert delegate.calls == 0


def test_context_token_is_removed_after_delegate_exception() -> None:
    reader, repo, identity, corpora, as_of, token = _fixture()

    def explode():
        raise ValueError("delegate failure")

    bound = RequestBoundRetriever(repo, _Delegate(explode), token)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="delegate failure"):
        bound.search(identity, "failure", corpora, as_of)
    reader.epoch += 1
    token_after = cache_release_token(repo, identity, corpora, as_of)  # type: ignore[arg-type]
    assert reader.captures == 2
    assert token_after.state_epoch == 8

def test_aborted_cache_write_cannot_poison_aba_reversion() -> None:
    reader, repo, identity, corpora, as_of, token_a = _fixture()

    class ChangingDelegate:
        def __init__(self):
            self.calls = 0

        def search(self, identity, text, corpus_ids, as_of, limit=8):
            self.calls += 1
            if self.calls == 1:
                reader.epoch += 1
                reader.release = "b" * 64
                return ["evidence-from-B"]
            return ["evidence-from-A"]

    delegate = ChangingDelegate()
    cached = CachedRetriever(repo, delegate, EvidenceQueryCache(), "ABA")  # type: ignore[arg-type]
    bound_a = RequestBoundRetriever(repo, cached, token_a)  # type: ignore[arg-type]
    with pytest.raises(CorpusConsistencyError):
        bound_a.search(identity, "same question", corpora, as_of)
    assert delegate.calls == 1

    reader.epoch += 1
    reader.release = token_a.release_id
    token_a_again = reader.capture(identity, corpora, as_of)
    assert token_a_again.release_id == token_a.release_id
    assert token_a_again.state_epoch != token_a.state_epoch
    bound_again = RequestBoundRetriever(repo, cached, token_a_again)  # type: ignore[arg-type]
    assert bound_again.search(identity, "same question", corpora, as_of) == ["evidence-from-A"]
    assert delegate.calls == 2

