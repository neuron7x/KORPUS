"""Immutable identity for one evidence-bearing corpus read state."""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from korpus.domain.models import Identity, RetrievedEvidence

_SCOPE_DOMAIN = b"korpus-corpus-read-scope-v1\0"
_EVIDENCE_DOMAIN = b"korpus-version-evidence-v1\0"
_RELEASE_DOMAIN = b"korpus-temporal-release-v1\0"


class CorpusConsistencyError(RuntimeError):
    """The corpus changed across a read boundary or its sealed evidence is invalid."""


@dataclass(frozen=True, slots=True)
class CorpusReadToken:
    state_epoch: int
    release_id: str
    as_of: date
    corpus_ids: frozenset[str]
    authorization_scope_id: str

    def __post_init__(self) -> None:
        if self.state_epoch < 0:
            raise ValueError("state_epoch must be non-negative")
        if len(self.release_id) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.release_id
        ):
            raise ValueError("release_id must be a SHA-256 hex digest")
        if len(self.authorization_scope_id) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.authorization_scope_id
        ):
            raise ValueError("authorization_scope_id must be a SHA-256 hex digest")


class CorpusSnapshotReader(Protocol):
    def capture(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
    ) -> CorpusReadToken: ...

    def validate(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
        token: CorpusReadToken,
    ) -> None: ...


class SnapshotRetriever(Protocol):
    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        token: CorpusReadToken,
        limit: int = 8,
    ) -> list[RetrievedEvidence]: ...


class _HashWriter(Protocol):
    def update(self, data: bytes) -> object: ...


def _frame(hasher: _HashWriter, value: str) -> None:
    encoded = value.encode("utf-8")
    hasher.update(len(encoded).to_bytes(8, "big"))
    hasher.update(encoded)


def token_audit_record(token: CorpusReadToken | None) -> dict[str, object] | None:
    if token is None:
        return None
    return {
        "state_epoch": token.state_epoch,
        "release_id": token.release_id,
        "as_of": token.as_of.isoformat(),
        "corpus_ids": sorted(token.corpus_ids),
        "authorization_scope_id": token.authorization_scope_id,
    }


def authorization_scope_id(identity: Identity, corpus_ids: frozenset[str]) -> str:
    """Commit a token to every identity attribute that can alter retrieval visibility."""
    digest = hashlib.sha256()
    digest.update(_SCOPE_DOMAIN)
    _frame(digest, identity.subject)
    _frame(digest, str(int(identity.clearance)))
    for values in (
        sorted(identity.roles),
        sorted(identity.corpora),
        sorted(identity.compartments),
        sorted(corpus_ids),
    ):
        _frame(digest, str(len(values)))
        for value in values:
            _frame(digest, value)
    return digest.hexdigest()


def release_identity_digest(rows: Iterable[tuple[str, str, str, str, str]]) -> str:
    """Commit the exact visible approved-version set to one canonical release identity.

    Tuples are `(document_id, version_id, source_hash, review_state, evidence_digest)`.
    Every field is framed independently and rows are set-normalized before sorting, so
    SQL join multiplicity and row order cannot change the identity while omission or
    alteration of any provenance-bearing field necessarily changes it.
    """
    unique = set(rows)
    digest = hashlib.sha256()
    digest.update(_RELEASE_DOMAIN)
    for document_id, version_id, source_hash, review_state, evidence_digest in sorted(unique):
        _frame(digest, document_id)
        _frame(digest, version_id)
        _frame(digest, source_hash)
        _frame(digest, review_state)
        _frame(digest, evidence_digest)
    return digest.hexdigest()


def version_evidence_digest(
    rows: Iterable[tuple[str, int, int | None, str | None, str, str]],
) -> str:
    """Digest the exact ordered span set and verify every stored text hash first.

    Input tuples are `(span_id, ordinal, page, section, text, text_hash)`. The span id
    and ordinal make insertion/deletion/reordering visible; nullable metadata is tagged
    before framing so `None` cannot collide with a present empty value; `text_hash` is
    accepted only after recomputing it from the stored text.
    """
    normalized = sorted(rows, key=lambda row: (row[1], row[0]))
    if not normalized:
        raise CorpusConsistencyError("an approved version cannot seal an empty evidence set")
    if len({row[0] for row in normalized}) != len(normalized):
        raise CorpusConsistencyError("duplicate span id in version evidence")
    if len({row[1] for row in normalized}) != len(normalized):
        raise CorpusConsistencyError("duplicate span ordinal in version evidence")

    digest = hashlib.sha256()
    digest.update(_EVIDENCE_DOMAIN)
    for span_id, ordinal, page, section, text, text_hash in normalized:
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if text_hash != expected:
            raise CorpusConsistencyError("stored span text_hash does not match stored text")
        _frame(digest, span_id)
        _frame(digest, str(ordinal))
        _frame(digest, "0" if page is None else f"1:{page}")
        _frame(digest, "0" if section is None else f"1:{section}")
        _frame(digest, text_hash)
    return digest.hexdigest()
