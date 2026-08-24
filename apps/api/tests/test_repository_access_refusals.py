"""Repository-level access decisions, exercised where they are made.

The API layer checks entitlements, but the repository checks them again — a corpus the
identity does not hold is filtered out of the query rather than out of the response.
The duplication is deliberate: a route added tomorrow that forgets the check must
still not be able to read another compartment's material.

Coverage recorded those second checks as branches nothing had taken, along with the
argument validation on the near-duplicate and hash lookups. A defence that has never
refused anything, sitting behind a defence that has, is the definition of a control
nobody can distinguish from its own absence.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from korpus.application.ingestion import ExtractionSettings
from korpus.application.policy import PolicyEngine
from korpus.composition import build_ingestion_service
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    DocumentCreate,
    Identity,
    VersionCreate,
)
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.infrastructure.repository import SqlRepository

CONTENT = b"Order No. 7. Basis: article 12.\n"


@pytest.fixture
def repository(tmp_path: Path) -> SqlRepository:
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'access.db'}",
        "access-audit",
        PolicyEngine(),
        tmp_path / "anchor.json",
    )
    repository.initialize()
    return repository


@pytest.fixture
def curator() -> Identity:
    return Identity(
        subject="curator",
        roles=frozenset({"admin", "curator", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public", "restricted-demo"}),
    )


@pytest.fixture
def outsider() -> Identity:
    """Authenticated, entitled to a corpus this document is not in."""
    return Identity(
        subject="outsider",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"training"}),
    )


@pytest.fixture
def ingested(repository: SqlRepository, curator: Identity, tmp_path: Path):
    service = build_ingestion_service(
        repository,
        LocalObjectStore(tmp_path / "objects"),
        PolicyEngine(),
        ExtractionSettings(False, "ukr"),
    )
    return service.ingest(
        curator,
        DocumentCreate(canonical_title="Order 7", issuer="Test Issuer", corpus_id="public"),
        VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA),
        "order.txt",
        "text/plain",
        CONTENT,
    )


def test_an_entitled_identity_reads_the_document(
    repository: SqlRepository, curator: Identity, ingested
) -> None:
    """The dual: the refusals below are vacuous if nobody can read anything."""
    assert repository.get_document(curator, ingested.document.id) is not None
    assert [d.id for d in repository.list_documents(curator)] == [ingested.document.id]


def test_listing_hides_documents_from_a_corpus_the_identity_does_not_hold(
    repository: SqlRepository, outsider: Identity, ingested
) -> None:
    """Not an error — an absence. Enumerable existence is itself disclosure."""
    assert repository.list_documents(outsider) == []


def test_get_document_returns_the_row_and_leaves_the_decision_to_the_caller(
    repository: SqlRepository, outsider: Identity, ingested
) -> None:
    """Stated because it is surprising, and because one caller had forgotten it.

    `list_documents` filters by corpus, clearance, classification and compartment;
    `get_document` does none of that — on PostgreSQL row-level security refuses first,
    and on SQLite nothing does. Every application-layer caller is therefore required
    to follow it with `policy.can_access_document`, which is asserted mechanically in
    test_gate_parity.py. This test pins the repository's half of that contract so a
    later change cannot quietly make the callers' checks redundant-looking.
    """
    assert repository.get_document(outsider, ingested.document.id) is not None


def test_a_document_that_does_not_exist_is_absent_rather_than_an_error(
    repository: SqlRepository, curator: Identity
) -> None:
    """Distinguishable errors for "denied" and "absent" leak the corpus contents."""
    assert repository.get_document(curator, uuid4()) is None


def test_near_duplicate_search_is_scoped_to_the_corpora_the_identity_holds(
    repository: SqlRepository, outsider: Identity, ingested
) -> None:
    """Otherwise a similarity probe reports whether material exists in a closed corpus."""
    fingerprint = ingested.version.content_fingerprint

    assert repository.find_near_duplicate(outsider, fingerprint, corpus_id="public") is None


def test_near_duplicate_search_finds_the_version_for_an_entitled_identity(
    repository: SqlRepository, curator: Identity, ingested
) -> None:
    found = repository.find_near_duplicate(
        curator, ingested.version.content_fingerprint, corpus_id="public"
    )

    assert found is not None
    match, similarity = found
    assert match.id == ingested.version.id
    assert similarity == pytest.approx(1.0)


@pytest.mark.parametrize("fingerprint", ["", "zz", "g" * 16, "ab" * 9, "ABCDEF0123456789"])
def test_a_malformed_fingerprint_is_refused(
    repository: SqlRepository, curator: Identity, fingerprint: str
) -> None:
    with pytest.raises(ValueError, match="invalid content fingerprint"):
        repository.find_near_duplicate(curator, fingerprint)


@pytest.mark.parametrize("threshold", [0.0, 0.49, 1.01, -1.0])
def test_a_similarity_threshold_outside_the_supported_range_is_refused(
    repository: SqlRepository, curator: Identity, threshold: float
) -> None:
    """Below 0.5 simhash similarity carries no signal; above 1.0 is not a similarity."""
    with pytest.raises(ValueError, match="invalid near-duplicate threshold"):
        repository.find_near_duplicate(curator, "0" * 16, minimum_similarity=threshold)


def test_identical_bytes_under_a_different_revision_are_a_different_version(
    repository: SqlRepository, curator: Identity, ingested
) -> None:
    """A re-issue is a distinct state of the document, not an upload of what we hold."""
    source_hash = hashlib.sha256(CONTENT).hexdigest()

    same = repository.find_version_by_hash(curator, source_hash, revision="1")
    other = repository.find_version_by_hash(curator, source_hash, revision="2")

    assert same is not None and same.id == ingested.version.id
    assert other is None


def test_a_hash_lookup_is_scoped_to_the_document_when_one_is_given(
    repository: SqlRepository, curator: Identity, ingested
) -> None:
    source_hash = hashlib.sha256(CONTENT).hexdigest()

    assert (
        repository.find_version_by_hash(
            curator, source_hash, document_id=ingested.document.id
        )
        is not None
    )
    assert repository.find_version_by_hash(curator, source_hash, document_id=uuid4()) is None


def test_a_hash_lookup_is_scoped_to_the_corpus_when_one_is_given(
    repository: SqlRepository, curator: Identity, ingested
) -> None:
    source_hash = hashlib.sha256(CONTENT).hexdigest()

    assert repository.find_version_by_hash(curator, source_hash, corpus_id="public") is not None
    assert repository.find_version_by_hash(curator, source_hash, corpus_id="training") is None


def test_bytes_nobody_uploaded_are_not_found(
    repository: SqlRepository, curator: Identity, ingested
) -> None:
    absent = hashlib.sha256(b"never uploaded").hexdigest()

    assert repository.find_version_by_hash(curator, absent) is None


def test_a_reviewer_cannot_transition_a_version_from_another_corpus(
    repository: SqlRepository, outsider: Identity, ingested, tmp_path: Path
) -> None:
    """Found 2026-08-05: holding a review role was enough, entitlement was not checked.

    `transition` fetched the version and the document with calls that filter by
    nothing, checked the role, and proceeded. On PostgreSQL row-level security would
    have refused first — which is why nothing here had ever noticed.
    """
    from korpus.domain.models import ReviewState, ReviewTransition

    reviewer_elsewhere = Identity(
        subject="reviewer-training",
        roles=frozenset({"user", "reviewer", "curator"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"training"}),
    )
    service = build_ingestion_service(
        repository,
        LocalObjectStore(tmp_path / "objects"),
        PolicyEngine(),
        ExtractionSettings(False, "ukr"),
    )

    with pytest.raises(PermissionError, match="cannot access target document"):
        service.transition(
            reviewer_elsewhere,
            ingested.version.id,
            ReviewTransition(
                target=ReviewState.METADATA_REVIEWED,
                note="metadata review by an outside corpus",
            ),
        )


def test_a_version_cannot_be_queued_against_a_document_in_another_corpus(
    repository: SqlRepository, ingested, tmp_path: Path
) -> None:
    """The same defect in the durable-ingestion path, found by the same predicate."""
    from korpus.application.ingestion_jobs import DurableIngestionCoordinator
    from korpus.infrastructure.ingestion_jobs import SqlIngestionJobQueue

    curator_elsewhere = Identity(
        subject="curator-training",
        roles=frozenset({"user", "curator", "admin"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"training"}),
    )
    staged = tmp_path / "staged.txt"
    staged.write_bytes(CONTENT)
    service = DurableIngestionCoordinator(
        SqlIngestionJobQueue(repository.engine),
        LocalObjectStore(tmp_path / "quarantine"),
        repository,
        PolicyEngine(),
        max_attempts=3,
    )

    with pytest.raises(PermissionError, match="cannot access target document"):
        service.submit_version(
            curator_elsewhere,
            ingested.document.id,
            VersionCreate(revision="2", authority=AuthorityClass.OFFICIAL_UA),
            filename="order.txt",
            mime_type="text/plain",
            path=staged,
            source_hash=hashlib.sha256(CONTENT).hexdigest(),
        )


def test_listing_hides_a_document_above_the_readers_clearance(
    repository: SqlRepository, curator: Identity, tmp_path: Path
) -> None:
    """The clearance filter in `list_documents`, exercised where it is written.

    It used to be covered incidentally: the same predicate appeared in the retrieval
    projection, the mutation catalogue replaced both occurrences at once, and a
    retrieval test killed the mutant. When the projection moved to
    retrieval_queries.py on 2026-08-05 the listing predicate was left with nothing
    holding it — the mutant survived, and the listing would have returned every
    document a reader's corpora contained, at any tier.
    """
    service = build_ingestion_service(
        repository,
        LocalObjectStore(tmp_path / "objects"),
        PolicyEngine(),
        ExtractionSettings(False, "ukr"),
    )
    service.ingest(
        curator,
        DocumentCreate(
            canonical_title="Restricted order",
            issuer="Test Issuer",
            corpus_id="public",
            access_tier=AccessTier.RESTRICTED,
        ),
        VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA),
        "restricted.txt",
        "text/plain",
        CONTENT,
    )
    reader = Identity(
        subject="reader",
        roles=frozenset({"user"}),
        clearance=AccessTier.AUTHENTICATED,
        corpora=frozenset({"public"}),
    )

    assert repository.list_documents(reader) == []
    assert [d.canonical_title for d in repository.list_documents(curator)] == [
        "Restricted order"
    ]
