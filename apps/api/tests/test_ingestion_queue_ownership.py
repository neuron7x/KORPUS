"""Ownership, lease validity and the reaper's race, in the durable job queue.

The queue is the only place where an ingestion job exists between the upload and the
worker. Three properties hold it together: a job is created by the actor it names, it
is readable only by that actor or an auditor, and a lease is either valid or refused.
Measured on 2026-08-28 none of the three had a test — 66.7% branch coverage, with every
uncovered branch a refusal or a lost race.

The reaper is the subtle one. It marks jobs whose lease expired with attempts exhausted
as dead-lettered, and its own comment states the property it needs: it must never win a
race against a worker that revived. That is asserted here by making the row change
between the reaper's select and its update.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from korpus.application.policy import PolicyEngine
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    DocumentCreate,
    Identity,
    IngestionJobKind,
    IngestionJobRecord,
    IngestionJobState,
    VersionCreate,
)
from korpus.infrastructure.ingestion_jobs import IngestionJobConflict, SqlIngestionJobQueue
from korpus.infrastructure.ingestion_schema import ingestion_jobs
from korpus.infrastructure.repository import SqlRepository
from sqlalchemy import update

CONTENT = b"Order No. 11. Basis: article 3.\n"
DIGEST = hashlib.sha256(CONTENT).hexdigest()


@pytest.fixture
def queue(tmp_path: Path) -> SqlIngestionJobQueue:
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'queue.db'}",
        "queue-audit-key",
        PolicyEngine(),
        tmp_path / "anchor.json",
    )
    repository.initialize()
    return SqlIngestionJobQueue(repository.engine)


@contextmanager
def _after_first_select(queue: SqlIngestionJobQueue, mutate) -> Iterator[None]:
    """Run `mutate` on the caller's own connection right after its first SELECT.

    Both races below need the row to move between a read and the guarded update that
    follows it, and both run inside a single `engine.begin()`. SQLite serialises
    writers, so a second connection would deadlock rather than race — the change has to
    be made on the same connection the code under test is already holding.
    """
    original_begin = queue.engine.begin

    class Intercepting:
        def __init__(self, connection: object) -> None:
            self._connection = connection
            self._selects = 0

        def __getattr__(self, name: str):
            return getattr(self._connection, name)

        def execute(self, statement, *args, **kwargs):
            result = self._connection.execute(statement, *args, **kwargs)
            if self._selects == 0 and str(statement).lstrip().upper().startswith("SELECT"):
                self._selects = 1
                mutate(self._connection)
            return result

    class Wrapping:
        def __init__(self, inner) -> None:
            self._inner = inner

        def __enter__(self):
            return Intercepting(self._inner.__enter__())

        def __exit__(self, *exc):
            return self._inner.__exit__(*exc)

    queue.engine.begin = lambda: Wrapping(original_begin())  # type: ignore[method-assign]
    try:
        yield
    finally:
        queue.engine.begin = original_begin  # type: ignore[method-assign]


def _identity(subject: str, *roles: str) -> Identity:
    return Identity(
        subject=subject,
        roles=frozenset({"user", *roles}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )


def _job(actor: Identity, **changes: object) -> IngestionJobRecord:
    values: dict[str, object] = {
        "kind": IngestionJobKind.DOCUMENT,
        "actor": actor,
        "document": DocumentCreate(
            canonical_title="Order 11", issuer="Test Issuer", corpus_id="public"
        ),
        "version": VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA),
        "filename": "order.txt",
        "mime_type": "text/plain",
        "source_hash": DIGEST,
        "staging_object_key": "quarantine/order.txt",
        "max_attempts": 3,
    }
    values.update(changes)
    return IngestionJobRecord(**values)  # type: ignore[arg-type]


def test_a_job_cannot_be_created_on_behalf_of_another_actor(
    queue: SqlIngestionJobQueue,
) -> None:
    """The row's actor becomes the worker's identity when the job later runs.

    Accepting a mismatch would let one authenticated caller queue work that executes,
    reads and writes as somebody else — an entitlement escalation with a receipt in
    the other person's name.
    """
    caller = _identity("caller")
    with pytest.raises(ValueError, match="job actor must match"):
        queue.create(caller, _job(_identity("someone-else")))


def test_an_unknown_job_id_reads_as_absent_rather_than_as_an_error(
    queue: SqlIngestionJobQueue,
) -> None:
    assert queue.get(_identity("caller"), uuid4()) is None


def test_another_actors_job_is_invisible_and_an_auditor_can_still_see_it(
    queue: SqlIngestionJobQueue,
) -> None:
    """Absent and forbidden are deliberately the same answer here.

    Distinguishing them would turn the endpoint into an oracle for job ids belonging to
    other subjects. The audit roles are the exception, because an audit that cannot see
    the row cannot verify the chain that names it.
    """
    owner = _identity("owner")
    created = queue.create(owner, _job(owner))

    assert queue.get(owner, created.id) is not None
    assert queue.get(_identity("stranger"), created.id) is None
    assert queue.get(_identity("inspector", "auditor"), created.id) is not None
    assert queue.get(_identity("root", "admin"), created.id) is not None


@pytest.mark.parametrize(
    ("worker_id", "lease"),
    [("", 30), ("   ", 30), ("worker-1", 4), ("worker-1", 0), ("worker-1", -30)],
)
def test_a_lease_that_cannot_be_honoured_is_refused(
    queue: SqlIngestionJobQueue, worker_id: str, lease: int
) -> None:
    """A nameless worker cannot be reaped, and a lease under five seconds expires
    before the work it covers can plausibly finish."""
    with pytest.raises(ValueError, match="invalid worker lease"):
        queue.claim(worker_id, lease_seconds=lease)


def test_an_empty_queue_hands_out_nothing(queue: SqlIngestionJobQueue) -> None:
    assert queue.claim("worker-1", lease_seconds=30) is None


def test_a_claim_whose_row_moved_underneath_it_is_refused(
    queue: SqlIngestionJobQueue,
) -> None:
    """The guarded UPDATE re-asserts state and attempts; two workers cannot both win.

    Without it the second claimant would overwrite the first one's lease, and the same
    payload would be ingested twice under two different attempt counters.
    """
    owner = _identity("owner")
    created = queue.create(owner, _job(owner))

    def bump_attempts(connection: object) -> None:
        connection.execute(  # type: ignore[attr-defined]
            update(ingestion_jobs).where(ingestion_jobs.c.id == str(created.id)).values(attempts=2)
        )

    with (
        _after_first_select(queue, bump_attempts),
        pytest.raises(IngestionJobConflict, match="claim changed concurrently"),
    ):
        queue.claim("worker-1", lease_seconds=30)


def test_the_reaper_dead_letters_only_an_expired_lease_with_attempts_exhausted(
    queue: SqlIngestionJobQueue,
) -> None:
    """Three conditions, all required: RUNNING, lease past, attempts at the ceiling."""
    owner = _identity("owner")
    created = queue.create(owner, _job(owner, max_attempts=1))
    claimed = queue.claim("worker-1", lease_seconds=5)
    assert claimed is not None

    assert queue.reap_orphaned_leases(now=datetime.now(UTC)) == []

    later = datetime.now(UTC) + timedelta(seconds=60)
    reaped = queue.reap_orphaned_leases(now=later)
    assert [job.id for job in reaped] == [created.id]
    assert reaped[0].state is IngestionJobState.DEAD_LETTER
    assert reaped[0].error_code == "orphaned_lease"
    assert reaped[0].lease_owner is None

    assert queue.reap_orphaned_leases(now=later) == []


def test_the_reaper_loses_to_a_worker_that_revived(queue: SqlIngestionJobQueue) -> None:
    """Its own comment states the property: it never wins a race against real progress.

    The lease is renewed on the reaper's own connection, between its select and the
    guarded update that follows — which is exactly what a late worker checking in looks
    like from inside that transaction. The update re-asserts the exact lease it read, so
    it must now match nothing, and a job with a live worker must not be dead-lettered.
    """
    owner = _identity("owner")
    created = queue.create(owner, _job(owner, max_attempts=1))
    assert queue.claim("worker-1", lease_seconds=5) is not None
    later = datetime.now(UTC) + timedelta(seconds=60)

    def revive(connection: object) -> None:
        # The worker checked in: it renewed its lease into the future. The row is still
        # RUNNING, so only the lease value distinguishes it from an abandoned job.
        connection.execute(  # type: ignore[attr-defined]
            update(ingestion_jobs)
            .where(ingestion_jobs.c.id == str(created.id))
            .values(lease_expires_at=later + timedelta(seconds=300))
        )

    with _after_first_select(queue, revive):
        reaped = queue.reap_orphaned_leases(now=later)

    assert reaped == [], "the reaper overwrote a job whose worker had checked in"
    survivor = queue.get(_identity("root", "admin"), created.id)
    assert survivor is not None
    assert survivor.state is IngestionJobState.RUNNING
    assert survivor.error_code is None


def test_an_expired_lease_with_attempts_left_is_not_dead_lettered(
    queue: SqlIngestionJobQueue,
) -> None:
    """Exhaustion is the third condition, and it is the one that decides retry vs. death.

    A worker that crashed on its first of three attempts leaves exactly the same row
    shape as one that exhausted them: RUNNING, lease in the past. Only the attempt
    counter separates a job that should be picked up again from a job that has failed
    for good. Reaping on the first two conditions alone would dead-letter every
    transient crash, and the retry budget would exist only on paper.
    """
    owner = _identity("owner")
    created = queue.create(owner, _job(owner, max_attempts=3))
    assert queue.claim("worker-1", lease_seconds=5) is not None

    later = datetime.now(UTC) + timedelta(seconds=60)
    assert queue.reap_orphaned_leases(now=later) == []

    survivor = queue.get(_identity("root", "admin"), created.id)
    assert survivor is not None
    assert survivor.state is IngestionJobState.RUNNING
    assert survivor.attempts == 1
    assert survivor.error_code is None
