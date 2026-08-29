"""Review transitions: the state guard, the classification floor and the clearance ceiling.

A review transition is the only way a document moves from quarantine into retrieval, and
`review_transitions.py` measured 80.6% branch coverage on 2026-08-28 with the refusing
side of each control untaken: the version that is not there, the state that moved under
the reviewer, the tier below what the classification requires, and the tier above what
the approver holds.

The last two are a pair and they fail in opposite directions. A tier below the
classification floor publishes material at a level its own marking forbids; a tier above
the approver's clearance lets a reviewer grant an access level they do not themselves
hold, which is privilege escalation with a review note attached.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.policy import PolicyEngine
from korpus.composition import build_ingestion_service
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentCreate,
    Identity,
    ReviewState,
    VersionCreate,
)
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.infrastructure.repository import NonRetryableWriteError, SqlRepository

CONTENT = b"Order No. 33. Basis: article 5.\n"


@pytest.fixture
def repository(tmp_path: Path) -> SqlRepository:
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'review.db'}",
        "review-audit-key",
        PolicyEngine(),
        tmp_path / "anchor.json",
    )
    repository.initialize()
    return repository


@pytest.fixture
def service(repository: SqlRepository, tmp_path: Path) -> IngestionService:
    return build_ingestion_service(
        repository,
        LocalObjectStore(tmp_path / "objects"),
        PolicyEngine(),
        ExtractionSettings(ocr_enabled=False, ocr_languages="ukr"),
    )


def _identity(subject: str, clearance: AccessTier = AccessTier.RESTRICTED) -> Identity:
    return Identity(
        subject=subject,
        roles=frozenset({"admin", "curator", "reviewer", "user"}),
        clearance=clearance,
        corpora=frozenset({"public"}),
    )


@pytest.fixture
def curator() -> Identity:
    return _identity("curator")


@pytest.fixture
def ingested(service: IngestionService, curator: Identity):
    return service.ingest(
        curator,
        DocumentCreate(canonical_title="Order 33", issuer="Test Issuer", corpus_id="public"),
        VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA),
        "order.txt",
        "text/plain",
        CONTENT,
    )


def test_a_version_that_does_not_exist_cannot_be_transitioned(
    repository: SqlRepository, curator: Identity
) -> None:
    with pytest.raises(LookupError, match="version not found"):
        repository.transition_version(
            curator,
            uuid4(),
            ReviewState.QUARANTINED,
            ReviewState.METADATA_REVIEWED,
            "review",
        )


def test_a_transition_from_a_state_the_version_is_no_longer_in_is_refused(
    repository: SqlRepository, curator: Identity, ingested
) -> None:
    """Two reviewers acting on one version must not both succeed.

    The expected state is asserted at read time and again in the guarded UPDATE. Without
    the first, the second reviewer overwrites a verdict they never saw; without the
    second, two concurrent transitions both write and one verdict vanishes.
    """
    repository.transition_version(
        curator,
        ingested.version.id,
        ReviewState.QUARANTINED,
        ReviewState.METADATA_REVIEWED,
        "first review",
    )
    with pytest.raises(NonRetryableWriteError, match="state changed concurrently"):
        repository.transition_version(
            curator,
            ingested.version.id,
            ReviewState.QUARANTINED,
            ReviewState.METADATA_REVIEWED,
            "second reviewer, stale view",
        )


def _advance_to_content_reviewed(repository: SqlRepository, actor: Identity, version_id) -> None:
    repository.transition_version(
        actor, version_id, ReviewState.QUARANTINED, ReviewState.METADATA_REVIEWED, "metadata"
    )
    repository.transition_version(
        actor,
        version_id,
        ReviewState.METADATA_REVIEWED,
        ReviewState.CONTENT_REVIEWED,
        "content",
        acknowledge_extraction_quality=True,
    )


def test_an_access_tier_below_the_documents_classification_is_refused(
    repository: SqlRepository, service: IngestionService, curator: Identity
) -> None:
    """The classification is the floor; the tier may sit at or above it, never under.

    A RESTRICTED document approved at PUBLIC tier is readable by everyone while still
    carrying its marking — the marking and the access decision would disagree, and the
    access decision is the one that runs.
    """
    restricted = service.ingest(
        curator,
        DocumentCreate(
            canonical_title="Restricted Order 34",
            issuer="Test Issuer",
            corpus_id="public",
            classification=Classification.RESTRICTED,
            access_tier=AccessTier.RESTRICTED,
        ),
        VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA),
        "restricted.txt",
        "text/plain",
        b"Restricted order text, distinct from the public one.\n",
    )
    _advance_to_content_reviewed(repository, curator, restricted.version.id)
    with pytest.raises(ValueError, match="below classification minimum"):
        repository.transition_version(
            curator,
            restricted.version.id,
            ReviewState.CONTENT_REVIEWED,
            ReviewState.APPROVED,
            "approve too low",
            access_tier=AccessTier.PUBLIC,
        )


def test_an_approver_cannot_grant_a_tier_above_their_own_clearance(
    repository: SqlRepository, curator: Identity, ingested
) -> None:
    """Escalation with a review note attached is still escalation."""
    _advance_to_content_reviewed(repository, curator, ingested.version.id)
    limited = _identity("reviewer-public", AccessTier.PUBLIC)
    with pytest.raises(PermissionError, match="cannot assign a tier above own clearance"):
        repository.transition_version(
            limited,
            ingested.version.id,
            ReviewState.CONTENT_REVIEWED,
            ReviewState.APPROVED,
            "approve above own clearance",
            access_tier=AccessTier.RESTRICTED,
        )


def test_rejecting_an_approved_version_takes_it_out_of_the_current_set(
    repository: SqlRepository, curator: Identity, ingested
) -> None:
    """`APPROVED -> REJECTED` is the transition the `is_current` clear exists for.

    Before approval a version is not current, so clearing the flag on any earlier
    rejection changes nothing — which is why an earlier version of this test could not
    tell whether the clear was there at all. Withdrawal of an approval is the case where
    it does work: the row was serving retrieval a moment ago, and after the rejection the
    document must have no current version rather than a rejected one.
    """
    _advance_to_content_reviewed(repository, curator, ingested.version.id)
    approved = repository.transition_version(
        curator,
        ingested.version.id,
        ReviewState.CONTENT_REVIEWED,
        ReviewState.APPROVED,
        "approved",
        access_tier=AccessTier.RESTRICTED,
    )
    assert approved.is_current is True

    rejected = repository.transition_version(
        curator,
        ingested.version.id,
        ReviewState.APPROVED,
        ReviewState.REJECTED,
        "approval withdrawn on review",
    )
    assert rejected.review_state is ReviewState.REJECTED
    assert rejected.is_current is False, (
        "a withdrawn approval must leave the current set, not merely change its label"
    )

    assert (
        repository.list_retrievable_spans(
            curator, frozenset({"public"}), date.today(), version_id=ingested.version.id
        )
        == []
    )


def test_an_approved_version_becomes_current(
    repository: SqlRepository, curator: Identity, ingested
) -> None:
    """The dual: if nothing can be approved, every refusal above is vacuous."""
    _advance_to_content_reviewed(repository, curator, ingested.version.id)
    approved = repository.transition_version(
        curator,
        ingested.version.id,
        ReviewState.CONTENT_REVIEWED,
        ReviewState.APPROVED,
        "approved",
        access_tier=AccessTier.RESTRICTED,
    )
    assert approved.review_state is ReviewState.APPROVED
    assert approved.is_current is True


def test_rescinding_a_version_that_was_never_approved_is_refused(
    repository: SqlRepository, curator: Identity, ingested
) -> None:
    """Rescission is an act on something in force. A draft was never in force.

    The two verbs are deliberately different: REJECTED is a reviewer's verdict during
    review, rescission is the issuing authority withdrawing a document that was already
    approved. Collapsing them would let a reviewer record an authority's act.
    """
    with pytest.raises(ValueError, match="only an approved version can be rescinded"):
        repository.rescind_version(curator, ingested.version.id, note="withdrawn by issuer")

    _advance_to_content_reviewed(repository, curator, ingested.version.id)
    with pytest.raises(ValueError, match="only an approved version can be rescinded"):
        repository.rescind_version(curator, ingested.version.id, note="withdrawn by issuer")


def test_an_approved_version_is_rescinded_once_and_not_twice(
    repository: SqlRepository, curator: Identity, ingested
) -> None:
    """Withdrawal is idempotent by refusal rather than by silence.

    A second rescission would write a second timestamp over the first, moving the date
    the document left force — which is the fact the whole record exists to preserve.
    """
    _advance_to_content_reviewed(repository, curator, ingested.version.id)
    repository.transition_version(
        curator,
        ingested.version.id,
        ReviewState.CONTENT_REVIEWED,
        ReviewState.APPROVED,
        "approved",
        access_tier=AccessTier.RESTRICTED,
    )

    rescinded = repository.rescind_version(curator, ingested.version.id, note="withdrawn by issuer")
    assert rescinded.rescinded_at is not None
    assert rescinded.review_state is ReviewState.APPROVED, (
        "rescission records an authority's act; it is not a review verdict"
    )

    with pytest.raises(ValueError, match="already rescinded"):
        repository.rescind_version(curator, ingested.version.id, note="withdrawn again")

    assert (
        repository.list_retrievable_spans(
            curator, frozenset({"public"}), date.today(), version_id=ingested.version.id
        )
        == []
    ), "a rescinded version must not answer queries"


def test_approving_a_version_that_supersedes_an_unapproved_predecessor_is_refused(
    repository: SqlRepository, service: IngestionService, curator: Identity, ingested
) -> None:
    """A supersession edge may only point at a version that was in force.

    Superseding a draft would retire nothing and leave the document with a version that
    claims to replace something never published — the retrieval projection joins on that
    edge, so the successor would answer as current while its predecessor never was.
    """
    predecessor = ingested
    successor = service.ingest_version(
        curator,
        predecessor.document.id,
        VersionCreate(
            revision="2",
            authority=AuthorityClass.OFFICIAL_UA,
            supersedes_version_id=predecessor.version.id,
        ),
        "order-2.txt",
        "text/plain",
        b"The second revision of the same order.\n",
    )
    _advance_to_content_reviewed(repository, curator, successor.version.id)

    with pytest.raises(ValueError, match="superseded version must be approved"):
        repository.transition_version(
            curator,
            successor.version.id,
            ReviewState.CONTENT_REVIEWED,
            ReviewState.APPROVED,
            "approve over an unapproved predecessor",
            access_tier=AccessTier.RESTRICTED,
        )


def test_a_version_that_supersedes_nothing_is_approved_without_a_predecessor_check(
    repository: SqlRepository, curator: Identity, ingested
) -> None:
    """The dual: the first version of a document supersedes nothing and must still pass."""
    _advance_to_content_reviewed(repository, curator, ingested.version.id)
    approved = repository.transition_version(
        curator,
        ingested.version.id,
        ReviewState.CONTENT_REVIEWED,
        ReviewState.APPROVED,
        "first approval",
        access_tier=AccessTier.RESTRICTED,
    )
    assert approved.review_state is ReviewState.APPROVED
    assert approved.supersedes_version_id is None
