"""Admission decisions on both ingestion paths, and the invariant that makes two of them
unreachable.

`IngestionService.ingest` creates a document; `ingest_version` adds a version to one that
exists. The two paths carry the same four checks — governance, corpus, compartments,
document access — and on 2026-08-28 the module measured 87.1% branch coverage with the
refusing side of each one untaken.

The comment inside `ingest` records what that costs: supersession pointing at another
document's version once took an approved order out of retrieval while it stayed
`is_current` in the database, found in destruction stage B3. That check is here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from korpus.application.ingestion import ExtractionSettings, IngestionService
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

CONTENT = b"Order No. 21. Basis: article 8.\n"
DIGEST = hashlib.sha256(CONTENT).hexdigest()


@pytest.fixture
def repository(tmp_path: Path) -> SqlRepository:
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'admission.db'}",
        "admission-audit-key",
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


@pytest.fixture
def curator() -> Identity:
    return Identity(
        subject="curator",
        roles=frozenset({"admin", "curator", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )


def _document(corpus: str = "public", compartments: frozenset[str] = frozenset()) -> DocumentCreate:
    return DocumentCreate(
        canonical_title="Order 21",
        issuer="Test Issuer",
        corpus_id=corpus,
        compartments=compartments,
    )


def _version(**changes: object) -> VersionCreate:
    values: dict[str, object] = {"revision": "1", "authority": AuthorityClass.OFFICIAL_UA}
    values.update(changes)
    return VersionCreate(**values)  # type: ignore[arg-type]


def test_an_entitled_curator_ingests(service: IngestionService, curator: Identity) -> None:
    """The dual: every refusal below is vacuous if nothing can be ingested at all."""
    result = service.ingest(
        curator, _document(), _version(), "order.txt", "text/plain", CONTENT
    )
    assert result.document.canonical_title == "Order 21"


def test_a_corpus_the_actor_does_not_hold_is_refused_on_creation(
    service: IngestionService,
) -> None:
    outsider = Identity(
        subject="curator-training",
        roles=frozenset({"user", "curator"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"training"}),
    )
    with pytest.raises(PermissionError, match="unassigned corpus"):
        service.ingest(outsider, _document("public"), _version(), "o.txt", "text/plain", CONTENT)


def test_a_compartment_the_actor_does_not_hold_is_refused_on_creation(
    service: IngestionService,
) -> None:
    """Corpus and compartment are separate axes; holding one is not holding the other."""
    partial = Identity(
        subject="curator-partial",
        roles=frozenset({"user", "curator"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
        compartments=frozenset({"alpha"}),
    )
    with pytest.raises(PermissionError, match="unowned compartments"):
        service.ingest(
            partial,
            _document("public", frozenset({"alpha", "bravo"})),
            _version(),
            "o.txt",
            "text/plain",
            CONTENT,
        )


def test_a_new_document_cannot_supersede_another_documents_version(
    service: IngestionService, curator: Identity
) -> None:
    """Destruction stage B3: a foreign upload took an approved order out of retrieval.

    Supersession is an edge inside one canonical document. On the creation path the
    document has no predecessors, so any target belongs to somebody else — and the
    superseded version stopped being retrievable while it stayed `is_current` in the
    database, which is a state no reader could explain.
    """
    existing = service.ingest(
        curator, _document(), _version(), "order.txt", "text/plain", CONTENT
    )
    with pytest.raises(ValueError, match="cannot supersede a version of another document"):
        service.ingest(
            curator,
            _document(),
            _version(supersedes_version_id=existing.version.id),
            "other.txt",
            "text/plain",
            b"A different order entirely.\n",
        )


def test_a_version_for_an_unknown_document_is_a_lookup_failure(
    service: IngestionService, curator: Identity
) -> None:
    with pytest.raises(LookupError, match="document not found"):
        service.ingest_version(
            curator, uuid4(), _version(revision="2"), "o.txt", "text/plain", CONTENT
        )


def test_a_version_for_a_document_in_another_corpus_is_refused(
    service: IngestionService, curator: Identity
) -> None:
    """`get_document` returns the row; it does not decide access."""
    existing = service.ingest(
        curator, _document(), _version(), "order.txt", "text/plain", CONTENT
    )
    outsider = Identity(
        subject="curator-training",
        roles=frozenset({"user", "curator", "admin"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"training"}),
    )
    with pytest.raises(PermissionError, match="cannot access target document"):
        service.ingest_version(
            outsider,
            existing.document.id,
            _version(revision="2"),
            "o.txt",
            "text/plain",
            b"Another revision.\n",
        )


def test_controlled_ingestion_cannot_be_configured_without_a_governance_profile(
    repository: SqlRepository, tmp_path: Path
) -> None:
    """The constructor is what makes the two `require_corpus_governance` arms unreachable.

    Both `ingest` and `ingest_version` carry `elif self.require_corpus_governance: raise`,
    and neither can be taken: an instance in that state cannot be built. The check is kept
    as a second line for anyone who mutates the attribute after construction; what is
    tested is the invariant that makes it redundant.
    """
    for flag, message in (
        ("require_corpus_governance", "corpus governance profile"),
        ("require_reviewer_credentials", "reviewer credential enforcement"),
        ("require_source_signature", "source signature enforcement"),
    ):
        with pytest.raises(ValueError, match=message):
            build_ingestion_service(
                repository,
                LocalObjectStore(tmp_path / "objects"),
                PolicyEngine(),
                ExtractionSettings(ocr_enabled=False, ocr_languages="ukr"),
                **{flag: True},  # type: ignore[arg-type]
            )


def test_a_document_with_compartments_writes_them_as_rows(
    service: IngestionService, repository: SqlRepository
) -> None:
    """Compartments are a separate table, not a column: access is a join, not a string.

    An empty set writes no rows, which is why the branch that writes them had never been
    taken — every earlier test ingested an uncompartmented document.
    """
    from korpus.infrastructure.schema import document_compartments
    from sqlalchemy import select

    cleared = Identity(
        subject="curator-alpha",
        roles=frozenset({"admin", "curator", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
        compartments=frozenset({"alpha", "bravo"}),
    )
    result = service.ingest(
        cleared,
        _document("public", frozenset({"alpha", "bravo"})),
        _version(),
        "order.txt",
        "text/plain",
        CONTENT,
    )
    with repository.engine.connect() as connection:
        rows = connection.execute(
            select(document_compartments.c.compartment).where(
                document_compartments.c.document_id == str(result.document.id)
            )
        ).scalars().all()
    assert sorted(rows) == ["alpha", "bravo"]

    plain = service.ingest(
        cleared,
        _document("public"),
        _version(),
        "plain.txt",
        "text/plain",
        b"An uncompartmented order.\n",
    )
    with repository.engine.connect() as connection:
        none = connection.execute(
            select(document_compartments.c.compartment).where(
                document_compartments.c.document_id == str(plain.document.id)
            )
        ).scalars().all()
    assert none == []
