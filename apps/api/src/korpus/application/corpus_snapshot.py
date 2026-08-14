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
_RELEASE_DOMAIN = b"korpus-temporal-semantic-release-v2\0"


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


@dataclass(frozen=True, order=True, slots=True)
class SemanticReleaseMember:
    """Canonical answer-visible/decision-relevant state for one visible version."""

    document_id: str
    version_id: str
    source_hash: str
    review_state: str
    evidence_digest: str
    canonical_title: str
    corpus_id: str
    access_tier: str
    classification: str
    document_compartments: str
    visibility_compartments: str
    revision: str
    source_uri: str
    publication_date: str
    effective_from: str
    effective_until: str
    rescinded_at: str
    authority: str
    supersedes_version_id: str


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


def canonical_optional(value: str | None) -> str:
    """Tag absence so it cannot collide with a present empty string."""
    return "0" if value is None else f"1:{value}"


def canonical_set(values: Iterable[str]) -> str:
    """Length-frame a set so delimiters inside identifiers cannot create collisions."""
    normalized = sorted(set(values))
    digest = hashlib.sha256()
    digest.update(b"korpus-semantic-set-v1\0")
    for value in normalized:
        _frame(digest, value)
    return f"{len(normalized)}:{digest.hexdigest()}"


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
    """Commit every identity attribute that can alter retrieval visibility."""
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


def release_identity_digest(rows: Iterable[SemanticReleaseMember]) -> str:
    """Commit the versioned semantic projection of the exact visible release."""
    digest = hashlib.sha256()
    digest.update(_RELEASE_DOMAIN)
    for member in sorted(set(rows)):
        document_id = member.document_id
        version_id = member.version_id
        source_hash = member.source_hash
        review_state = member.review_state
        evidence_digest = member.evidence_digest
        _frame(digest, document_id)
        _frame(digest, version_id)
        _frame(digest, source_hash)
        _frame(digest, review_state)
        _frame(digest, evidence_digest)
        _frame(digest, member.canonical_title)
        _frame(digest, member.corpus_id)
        _frame(digest, member.access_tier)
        _frame(digest, member.classification)
        _frame(digest, member.document_compartments)
        _frame(digest, member.visibility_compartments)
        _frame(digest, member.revision)
        _frame(digest, member.source_uri)
        _frame(digest, member.publication_date)
        _frame(digest, member.effective_from)
        _frame(digest, member.effective_until)
        _frame(digest, member.rescinded_at)
        _frame(digest, member.authority)
        _frame(digest, member.supersedes_version_id)
    return digest.hexdigest()


def version_evidence_digest(
    rows: Iterable[tuple[str, int, int | None, str | None, str, str]],
) -> str:
    """Digest the exact ordered span set and verify every stored text hash first."""
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
