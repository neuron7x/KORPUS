"""The durable-ingestion coordinator's access decisions and its worker's guards.

`DurableIngestionCoordinator` is the second door on the ingestion path: the route
checks entitlements, and this layer checks them again against the actor's own corpora
and compartments before anything is written to quarantine. On 2026-08-28 the module sat
at 43.8% branch coverage — the corpus check, the compartment check and both
malformed-job guards in the worker had never been taken.

The comment in `submit_version` records why that matters here specifically: the same
check was once missing from this method, and PostgreSQL row-level security hid the gap
on one dialect while SQLite would have shown it. A control that only one database
enforces is not an application control, and an untested one is indistinguishable from
a control that was quietly removed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from korpus.application.ingestion import ExtractionSettings
from korpus.application.ingestion_jobs import DurableIngestionCoordinator, IngestionWorker
from korpus.application.policy import PolicyEngine
from korpus.composition import build_ingestion_service
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    DocumentCreate,
    Identity,
    IngestionJobKind,
    IngestionJobRecord,
    VersionCreate,
)
from korpus.infrastructure.ingestion_jobs import SqlIngestionJobQueue
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.schema import metadata
from pydantic import ValidationError
from sqlalchemy import update

CONTENT = b"Order No. 7. Basis: article 12.\n"


@pytest.fixture
def repository(tmp_path: Path) -> SqlRepository:
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'jobs.db'}",
        "coordinator-audit-key",
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
        corpora=frozenset({"public"}),
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


@pytest.fixture
def coordinator(repository: SqlRepository, tmp_path: Path) -> DurableIngestionCoordinator:
    return DurableIngestionCoordinator(
        SqlIngestionJobQueue(repository.engine),
        LocalObjectStore(tmp_path / "quarantine"),
        repository,
        PolicyEngine(),
        max_attempts=3,
    )


@pytest.fixture
def staged(tmp_path: Path) -> Path:
    path = tmp_path / "staged.txt"
    path.write_bytes(CONTENT)
    return path


def _document(corpus: str = "public", compartments: frozenset[str] = frozenset()) -> DocumentCreate:
    return DocumentCreate(
        canonical_title="Order 9",
        issuer="Test Issuer",
        corpus_id=corpus,
        compartments=compartments,
    )


def _version() -> VersionCreate:
    return VersionCreate(revision="2", authority=AuthorityClass.OFFICIAL_UA)


def _submit_kwargs(staged: Path) -> dict[str, object]:
    return {
        "filename": "order.txt",
        "mime_type": "text/plain",
        "path": staged,
        "source_hash": hashlib.sha256(CONTENT).hexdigest(),
    }


def test_an_entitled_curator_queues_a_document(
    coordinator: DurableIngestionCoordinator, curator: Identity, staged: Path
) -> None:
    """The dual. Without it every refusal below could come from a broken constructor."""
    job = coordinator.submit_document(curator, _document(), _version(), **_submit_kwargs(staged))
    assert job.kind is IngestionJobKind.DOCUMENT
    assert job.staging_object_key


def test_a_corpus_the_actor_does_not_hold_is_refused_before_anything_is_staged(
    coordinator: DurableIngestionCoordinator, staged: Path, tmp_path: Path
) -> None:
    """Refusal precedes `put_path`: a rejected upload must leave no quarantine object."""
    outsider = Identity(
        subject="curator-training",
        roles=frozenset({"user", "curator"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"training"}),
    )
    with pytest.raises(PermissionError, match="unassigned corpus"):
        coordinator.submit_document(
            outsider, _document("public"), _version(), **_submit_kwargs(staged)
        )
    quarantine = tmp_path / "quarantine"
    assert not any(quarantine.rglob("*")) if quarantine.exists() else True


def test_a_compartment_the_actor_does_not_hold_is_refused(
    coordinator: DurableIngestionCoordinator, staged: Path
) -> None:
    """Corpus and compartment are separate axes: holding the corpus is not holding the tag."""
    partial = Identity(
        subject="curator-partial",
        roles=frozenset({"user", "curator"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
        compartments=frozenset({"alpha"}),
    )
    with pytest.raises(PermissionError, match="unowned compartments"):
        coordinator.submit_document(
            partial,
            _document("public", frozenset({"alpha", "bravo"})),
            _version(),
            **_submit_kwargs(staged),
        )


def test_an_admin_may_cross_both_boundaries(
    coordinator: DurableIngestionCoordinator, staged: Path
) -> None:
    """Both refusals carry an admin exemption, and an exemption nothing takes is dead code."""
    admin = Identity(
        subject="root",
        roles=frozenset({"admin", "curator", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"training"}),
        compartments=frozenset(),
    )
    job = coordinator.submit_document(
        admin,
        _document("public", frozenset({"alpha"})),
        _version(),
        **_submit_kwargs(staged),
    )
    assert job.kind is IngestionJobKind.DOCUMENT


def test_a_version_for_an_unknown_document_is_a_lookup_failure_not_a_permission_one(
    coordinator: DurableIngestionCoordinator, curator: Identity, staged: Path
) -> None:
    """Distinguishing the two is deliberate: 404 and 403 answer different questions."""
    with pytest.raises(LookupError, match="document not found"):
        coordinator.submit_version(curator, uuid4(), _version(), **_submit_kwargs(staged))


def test_a_version_for_an_accessible_document_is_queued(
    coordinator: DurableIngestionCoordinator, curator: Identity, ingested, staged: Path
) -> None:
    """The accepting side of the access check that PostgreSQL RLS used to hide."""
    job = coordinator.submit_version(
        curator, ingested.document.id, _version(), **_submit_kwargs(staged)
    )
    assert job.kind is IngestionJobKind.VERSION
    assert job.document_id == ingested.document.id


def _worker(repository: SqlRepository, tmp_path: Path) -> IngestionWorker:
    return IngestionWorker(
        SqlIngestionJobQueue(repository.engine),
        LocalObjectStore(tmp_path / "quarantine"),
        None,  # type: ignore[arg-type]
        repository,
        worker_id="worker-guard",
        lease_seconds=30,
    )


def test_an_idle_queue_reports_no_work_rather_than_failing(
    repository: SqlRepository, tmp_path: Path
) -> None:
    execution = _worker(repository, tmp_path).run_once()
    assert execution.claimed is False
    assert execution.job is None


def test_a_corrupted_job_row_is_refused_at_claim_not_at_execution(
    repository: SqlRepository, curator: Identity, tmp_path: Path
) -> None:
    """`run_once` has two guards for a job whose kind and payload disagree. Neither is
    reachable, and this test is the proof rather than an assumption.

    `IngestionJobRecord.validate_target` runs on every construction, and `claim` builds
    the record from the row before the worker ever sees it. Nulling `document_json` and
    `document_id` directly in the database — the only way past the model on the write
    side — makes `claim` raise, so the worker's own `document is None` branch cannot be
    taken. The guards stay as type narrowing for mypy and are marked no-cover; what is
    tested is the control that makes them unreachable.
    """
    store = LocalObjectStore(tmp_path / "quarantine")
    staged = tmp_path / "payload.txt"
    staged.write_bytes(CONTENT)
    digest = hashlib.sha256(CONTENT).hexdigest()
    queue = SqlIngestionJobQueue(repository.engine)
    queue.create(
        curator,
        IngestionJobRecord(
            kind=IngestionJobKind.DOCUMENT,
            actor=curator,
            document=_document(),
            version=_version(),
            filename="payload.txt",
            mime_type="text/plain",
            source_hash=digest,
            staging_object_key=store.put_path(staged, digest, "payload.txt"),
            max_attempts=1,
        ),
    )

    jobs = metadata.tables["ingestion_jobs"]
    with repository.engine.begin() as connection:
        connection.execute(update(jobs).values(document_json=None, document_id=None))

    with pytest.raises(ValidationError, match="requires document payload only"):
        queue.claim("worker-guard", lease_seconds=30)


def test_a_kind_and_payload_that_disagree_cannot_be_constructed(curator: Identity) -> None:
    """The same invariant at the other end: the model refuses, so no such row is written."""
    common: dict[str, object] = {
        "actor": curator,
        "version": _version(),
        "filename": "payload.txt",
        "mime_type": "text/plain",
        "source_hash": "a" * 64,
        "staging_object_key": "quarantine/key",
        "max_attempts": 1,
    }
    with pytest.raises(ValidationError, match="document payload only"):
        IngestionJobRecord(kind=IngestionJobKind.DOCUMENT, **common)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="document_id only"):
        IngestionJobRecord(kind=IngestionJobKind.VERSION, **common)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="document_id only"):
        IngestionJobRecord(
            kind=IngestionJobKind.VERSION,
            document=_document(),
            document_id=uuid4(),
            **common,  # type: ignore[arg-type]
        )
