"""Actual app/authz-role proof for the queue's trusted PostgreSQL identity boundary.

The owner URL is used only by the existing disposable-suite reset. Every queue read,
write, worker transition and forged-claim probe runs as the non-owner application role.
Synthetic completion metadata tests queue persistence, not document ingestion or scanning.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from korpus.domain.models import (
    AuthorityClass,
    DocumentCreate,
    DocumentRecord,
    DocumentVersionRecord,
    Identity,
    IngestionJobKind,
    IngestionJobRecord,
    IngestionJobState,
    IngestResult,
    VersionCreate,
)
from korpus.infrastructure.ingestion_jobs import IngestionJobConflict, SqlIngestionJobQueue
from korpus.infrastructure.ingestion_schema import ingestion_jobs
from korpus.infrastructure.rls_repository import RlsBoundSqlRepository
from sqlalchemy import insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from apps.api.tests import conftest

pytestmark = pytest.mark.postgres
OWNER = Identity(subject="queue-owner", roles=frozenset({"curator"}))
STRANGER = Identity(subject="queue-stranger", roles=frozenset({"user"}))
AUDITOR = Identity(subject="queue-auditor", roles=frozenset({"auditor"}))
CONTENT = b"The archive label is blue.\n"


@pytest.fixture
def postgres_queue(tmp_path: Path) -> Iterator[tuple[RlsBoundSqlRepository, SqlIngestionJobQueue]]:
    app_url = os.getenv("KORPUS_TEST_DATABASE_URL")
    if not app_url:
        pytest.skip("native queue acceptance requires the disposable PostgreSQL suite")
    owner_url = os.getenv("KORPUS_TEST_DATABASE_ADMIN_URL")
    authz_url = os.getenv("KORPUS_AUTHZ_DATABASE_URL")
    assert owner_url and authz_url, "native queue acceptance requires separate owner/authz URLs"
    if app_url != conftest.POSTGRES_SUITE_URL or owner_url != conftest.POSTGRES_ADMIN_URL:
        pytest.fail("suite reset configuration changed after conftest loaded")
    app, owner, authz = map(make_url, (app_url, owner_url, authz_url))
    assert app.database in {"korpus_suite", "korpus_coverage", "korpus_test"}, (
        "refusing to reset a database outside the disposable suite namespaces"
    )
    assert (
        all(url.username for url in (app, owner, authz))
        and len({app.username, owner.username, authz.username}) == 3
    ), "application, owner and authorization broker must use distinct logins"
    assert all(
        url.get_backend_name() == "postgresql"
        and (url.host, url.port, url.database) == (app.host, app.port, app.database)
        for url in (app, owner, authz)
    ), "all identities must target the same isolated PostgreSQL database"
    conftest.reset_database()
    repository = RlsBoundSqlRepository(
        app_url,
        "queue-native-rls-audit-key",
        authz_database_url=authz_url,
        audit_anchor_path=tmp_path / "anchor.json",
        pool_size=1,
        max_overflow=0,
    )
    try:
        repository.initialize(create_schema=False)
        with repository.engine.connect() as connection:
            role = connection.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            ).one()
        assert role.current_user == app.username == "korpus_app"
        assert role.rolsuper is False and role.rolbypassrls is False
        yield (
            repository,
            SqlIngestionJobQueue(
                repository.engine, bind_identity=repository._apply_postgres_identity
            ),
        )
    finally:
        repository.close()
        conftest.reset_database()


def _job(*, max_attempts: int = 3) -> IngestionJobRecord:
    return IngestionJobRecord(
        kind=IngestionJobKind.DOCUMENT,
        actor=OWNER,
        document=DocumentCreate(canonical_title="Archive label", issuer="Synthetic fixture"),
        version=VersionCreate(revision="1", authority=AuthorityClass.ANALYTICAL),
        filename="archive.txt",
        mime_type="text/plain",
        source_hash=hashlib.sha256(CONTENT).hexdigest(),
        staging_object_key="quarantine/archive.txt",
        max_attempts=max_attempts,
    )


def _result() -> IngestResult:
    document = DocumentRecord(
        **DocumentCreate(canonical_title="Archive label", issuer="Synthetic fixture").model_dump()
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1",
        source_hash=hashlib.sha256(CONTENT).hexdigest(),
        object_key="objects/archive.txt",
        mime_type="text/plain",
        authority=AuthorityClass.ANALYTICAL,
    )
    return IngestResult(
        document=document, version=version, span_count=1, extraction_method="queue-fixture"
    )


def test_native_queue_lifecycle_and_ownership(postgres_queue) -> None:
    _, queue = postgres_queue
    job = queue.create(OWNER, _job())
    assert queue.get(OWNER, job.id) == job
    assert queue.get(STRANGER, job.id) is None
    assert queue.get(AUDITOR, job.id) == job
    unrelated_worker = Identity(subject="unrelated-worker", roles=frozenset({"worker"}))
    assert queue.get(unrelated_worker, job.id) is None
    now = datetime.now(UTC)
    claimed = queue.claim("worker-a", lease_seconds=5, now=now)
    assert claimed is not None and claimed.id == job.id
    assert claimed.state is IngestionJobState.RUNNING and claimed.attempts == 1
    assert claimed.lease_owner == "worker-a"
    result = _result()
    with pytest.raises(IngestionJobConflict, match="does not own"):
        queue.complete("wrong-worker", job.id, result)
    with pytest.raises(IngestionJobConflict, match="does not own"):
        queue.fail("wrong-worker", job.id, "wrong", "wrong owner", retryable=True)
    assert queue.get(OWNER, job.id).lease_owner == "worker-a"
    failed = queue.fail("worker-a", job.id, "transient", "retry fixture", retryable=True)
    assert failed.state is IngestionJobState.RETRYABLE and failed.lease_owner is None
    reclaimed = queue.claim("worker-b", lease_seconds=5, now=now + timedelta(seconds=1))
    assert reclaimed is not None and reclaimed.id == job.id and reclaimed.attempts == 2
    completed = queue.complete("worker-b", job.id, result)
    assert completed.state is IngestionJobState.SUCCEEDED and completed.lease_owner is None
    assert queue.get(OWNER, job.id).result == result

    orphan = queue.create(OWNER, _job(max_attempts=1))
    claimed = queue.claim("orphaned-worker", lease_seconds=5, now=now)
    assert claimed is not None and claimed.id == orphan.id
    later = now + timedelta(seconds=6)
    reaped = queue.reap_orphaned_leases(now=later)
    assert [record.id for record in reaped] == [orphan.id]
    assert reaped[0].state is IngestionJobState.DEAD_LETTER
    assert reaped[0].error_code == "orphaned_lease"
    assert queue.get(OWNER, orphan.id).state is IngestionJobState.DEAD_LETTER
    assert queue.reap_orphaned_leases(now=later) == []
    assert queue.claim("idle-worker", lease_seconds=5, now=later) is None


@pytest.mark.parametrize("bind_stranger", [False, True])
def test_native_forged_session_claims_cannot_read_or_enqueue(postgres_queue, bind_stranger) -> None:
    repository, queue = postgres_queue
    original = queue.create(OWNER, _job())
    forged = _job()
    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, OWNER)
        assert connection.execute(select(ingestion_jobs.c.id)).scalars().all() == [str(original.id)]
        backend = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
    with pytest.raises(DBAPIError) as denied, repository.engine.begin() as connection:
        # Return to the same pooled backend in a new transaction: owner claims must expire.
        assert connection.execute(text("SELECT pg_backend_pid()")).scalar_one() == backend
        if bind_stranger:
            repository._apply_postgres_identity(connection, STRANGER)
        connection.execute(
            text(
                "SELECT set_config('korpus.subject', :subject, true), "
                "set_config('korpus.roles', 'admin,curator,worker', true)"
            ),
            {"subject": OWNER.subject},
        )
        # Direct SQL proves RLS denial independently of queue.get's Python owner filter.
        assert connection.execute(select(ingestion_jobs.c.id)).all() == []
        connection.execute(insert(ingestion_jobs).values(**queue._values(forged)))
    assert getattr(denied.value.orig, "sqlstate", None) == "42501"
    assert queue.get(OWNER, original.id) == original
    assert queue.get(OWNER, forged.id) is None
