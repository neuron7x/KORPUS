"""One captured token and reader authority across nested retrieval boundaries."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date

from korpus.application.corpus_snapshot import (
    CorpusConsistencyError,
    CorpusReadToken,
    CorpusSnapshotReader,
    attached_snapshot_reader,
    authorization_scope_id,
    release_token,
)
from korpus.domain.models import Identity, RetrievedEvidence

ReadArguments = tuple[Identity, frozenset[str], date]


def _reader(repository: object) -> CorpusSnapshotReader:
    reader = attached_snapshot_reader(repository)
    if reader is None:
        raise CorpusConsistencyError("corpus snapshot reader disappeared during answer")
    if getattr(reader, "repository", repository) is not repository:
        raise CorpusConsistencyError("snapshot reader repository authority mismatched")
    return reader


@dataclass(frozen=True)
class _ReadScope:
    reader: CorpusSnapshotReader
    token: CorpusReadToken
    arguments: ReadArguments
    repository: object | None

    def require(
        self, reader: CorpusSnapshotReader, arguments: ReadArguments, repository: object | None
    ) -> None:
        if self.reader is not reader or (
            self.repository is not None
            and repository is not None
            and self.repository is not repository
        ):
            raise CorpusConsistencyError("retrieval borrowed a different snapshot authority")
        identity, corpus_ids, as_of = arguments
        authorized = frozenset(corpus_ids.intersection(identity.corpora))
        if (self.token.as_of, self.token.corpus_ids, self.token.authorization_scope_id) != (
            as_of, authorized, authorization_scope_id(identity, authorized)
        ):
            raise CorpusConsistencyError("cached retrieval scope differs from answer snapshot")

    def validate(self) -> None:
        if _reader(self.repository) is not self.reader:
            raise CorpusConsistencyError("corpus snapshot authority changed during retrieval")
        self.reader.validate(*self.arguments, self.token)


_ACTIVE_SCOPE: ContextVar[_ReadScope | None] = ContextVar("korpus_corpus_read_scope", default=None)


@contextmanager
def _bind_scope(scope: _ReadScope) -> Iterator[CorpusReadToken]:
    scope.validate()
    context = _ACTIVE_SCOPE.set(scope)
    try:
        yield scope.token
        scope.validate()
    finally:
        _ACTIVE_SCOPE.reset(context)


def _read_scope(
    reader: CorpusSnapshotReader,
    arguments: ReadArguments,
    token: CorpusReadToken | None,
    repository: object | None,
) -> AbstractContextManager[CorpusReadToken]:
    active = _ACTIVE_SCOPE.get()
    if active is not None and token is not None and token != active.token:
        raise CorpusConsistencyError("nested retrieval replaced answer snapshot")
    if active is not None:
        active.require(reader, arguments, repository)
        token, repository = active.token, active.repository if repository is None else repository
    if token is None:
        token = reader.capture(*arguments)
    return _bind_scope(_ReadScope(reader, token, arguments, repository))


@contextmanager
def repository_read_scope(
    repository: object, arguments: ReadArguments, token: CorpusReadToken | None = None
) -> Iterator[CorpusReadToken]:
    with _read_scope(_reader(repository), arguments, token, repository) as selected:
        yield selected


def read_with_token(
    reader: CorpusSnapshotReader,
    token: CorpusReadToken,
    arguments: ReadArguments,
    action: Callable[[], list[RetrievedEvidence]],
) -> list[RetrievedEvidence]:
    with _read_scope(reader, arguments, token, getattr(reader, "repository", None)):
        return action()


def cache_release_token(
    repository: object, identity: Identity, corpus_ids: frozenset[str], as_of: date
) -> CorpusReadToken:
    active = _ACTIVE_SCOPE.get()
    if active is None:
        return release_token(repository, identity, corpus_ids, as_of)
    active.require(_reader(repository), (identity, corpus_ids, as_of), repository)
    return active.token


def validate_active_read(repository: object | None = None) -> None:
    active = _ACTIVE_SCOPE.get()
    if active is None:
        return
    if repository is not None:
        active.require(_reader(repository), active.arguments, repository)
    active.validate()
