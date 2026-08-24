"""What a soldier's client sees when a dependency is down: a 503 to retry, never a 500.

Each test forces one dependency to fail the way it fails in the field — the database
restarting, the object store unreachable, the upload spool full — and asserts the reader
gets a clean, retryable refusal rather than an uncaught exception with a stack trace. The
distinction is the whole point: a 500 tells a client the system is broken; a 503 with
Retry-After tells it to come back, which is the truth of a transient outage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from korpus.application.ports import ObjectStoreUnavailable
from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity
from korpus.main import create_app
from korpus.security.auth import get_identity

from apps.api.tests.conftest import IdentityProvider

ADMIN = Identity(
    subject="reliability-admin",
    roles=frozenset({"admin", "curator", "reviewer", "user", "auditor"}),
    clearance=AccessTier.RESTRICTED,
    corpora=frozenset({"public"}),
)


@pytest.fixture
def client(tmp_path: Path) -> Any:
    settings = Settings(
        environment="test",
        schema_mode="auto",
        database_url=f"sqlite:///{tmp_path / 'rel.db'}",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        audit_hmac_key="reliability-key",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        max_upload_bytes=4 * 1024 * 1024,
    )
    app = create_app(settings)
    app.dependency_overrides[get_identity] = IdentityProvider(ADMIN)
    # raise_server_exceptions=False so an uncaught 500 is observed as a response the way a
    # real client sees it, rather than re-raised into the test — which is exactly the
    # failure mode under test.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_database_down_is_a_503_not_a_500(client: Any, monkeypatch) -> None:
    from sqlalchemy.exc import OperationalError

    def unavailable(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    # list_documents reads through the repository; force its query to fail like a restart.
    monkeypatch.setattr(client.app.state.repository, "list_documents", unavailable)
    response = client.get("/v1/documents")
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["reason"] == "database"
    assert response.headers["Retry-After"]


def test_object_store_unavailable_is_a_503_not_a_500(client: Any, monkeypatch) -> None:
    def unreachable(*args, **kwargs):
        raise ObjectStoreUnavailable("object store unreachable: EndpointConnectionError")

    monkeypatch.setattr(client.app.state.object_store, "healthcheck", unreachable)
    # /ready exercises the object store healthcheck; an unreachable store must degrade, not crash.
    response = client.get("/ready")
    assert response.status_code == 503
    # Either the readiness reason or the object-store handler — both are clean 503s, never 500.
    assert response.status_code != 500


def test_a_full_upload_spool_is_a_503_not_a_500(client: Any, monkeypatch) -> None:
    import os as _os

    import korpus.api.routes_corpus as routes

    class _FullDisk:
        """A spool handle on a tmpfs with no room left: every write is ENOSPC."""

        def __enter__(self): return self
        def __exit__(self, *args): return False
        def write(self, _data): raise OSError(28, "No space left on device")
        def flush(self): pass
        def fileno(self): return 0

    def fdopen(descriptor, *args, **kwargs):
        _os.close(descriptor)  # take ownership as the real fdopen would, then fail on write
        return _FullDisk()

    monkeypatch.setattr(routes.os, "fdopen", fdopen)
    response = client.post(
        "/v1/documents/ingest",
        data={
            "document_json": '{"canonical_title":"Настанова тест","corpus_id":"public",'
            '"issuer":"ГШ","jurisdiction":"UA","document_type":"order","access_tier":0,'
            '"classification":"public"}',
            "version_json": '{"revision":"1.0","authority":"official_ua",'
            '"publication_date":"2020-01-01"}',
        },
        files={"file": ("d.txt", b"a" * 4096, "text/plain")},
    )
    assert response.status_code == 503, response.text
    assert response.headers["Retry-After"]


def test_a_crashed_worker_leaves_no_zombie_running_job(tmp_path: Path) -> None:
    """A worker that dies mid-job on its last attempt leaves a RUNNING row that claim can
    never re-pick. The reaper moves it to dead_letter so a soldier's document is not stuck
    RUNNING forever with no record of why it never appeared.
    """
    from datetime import UTC, datetime, timedelta

    from korpus.application.policy import PolicyEngine
    from korpus.domain.models import IngestionJobState
    from korpus.infrastructure.ingestion_jobs import SqlIngestionJobQueue, ingestion_jobs
    from korpus.infrastructure.repository import SqlRepository
    from sqlalchemy import update

    repo = SqlRepository(
        f"sqlite:///{tmp_path / 'reap.db'}", "reap-key", PolicyEngine(),
        tmp_path / "reap-anchor.json",
    )
    repo.initialize()
    try:
        from apps.api.tests.helpers import ingest_text  # noqa: F401 - ensures fixtures import

        queue = SqlIngestionJobQueue(repo.engine)
        # Seed a job, claim it (RUNNING), then simulate a crash: force it to the ceiling
        # with an expired lease directly, the state claim() will not re-pick.
        from apps.api.tests.tenancy_fixtures import reader  # reuse a valid Identity
        actor = reader("worker-subject")
        from korpus.domain.models import (
            DocumentCreate,
            IngestionJobKind,
            IngestionJobRecord,
            VersionCreate,
        )

        job = IngestionJobRecord(
            kind=IngestionJobKind.DOCUMENT,
            actor=actor,
            document=DocumentCreate(
                canonical_title="Настанова", corpus_id="public", issuer="ГШ",
                jurisdiction="UA", document_type="order", access_tier=0, classification="public",
            ),
            version=VersionCreate(revision="1.0", authority="official_ua"),
            filename="d.txt", mime_type="text/plain", source_hash="a" * 64,
            staging_object_key="00/00/" + "a" * 64, max_attempts=1,
        )
        queue.create(actor, job)
        claimed = queue.claim("worker-1", lease_seconds=5)
        assert claimed is not None and claimed.state is IngestionJobState.RUNNING

        # The crash: lease expired, attempts at the ceiling, still RUNNING.
        with repo.engine.begin() as connection:
            connection.execute(
                update(ingestion_jobs)
                .where(ingestion_jobs.c.id == str(job.id))
                .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        assert queue.claim("worker-2", lease_seconds=5) is None, "claim re-picked an exhausted job"

        # A second job that still has an attempt left, also with an expired lease: this one
        # belongs to `claim`, not the reaper. The reaper must leave it alone — the mutant
        # that reaps on `attempts >= 0` would wrongly bury it, and dies here.
        live = job.model_copy(update={
            "id": __import__("uuid").uuid4(), "max_attempts": 3,
            "staging_object_key": "11/11/" + "b" * 64, "source_hash": "b" * 64,
        })
        queue.create(actor, live)
        queue.claim("worker-live", lease_seconds=5)  # attempts now 1 of 3
        with repo.engine.begin() as connection:
            connection.execute(
                update(ingestion_jobs)
                .where(ingestion_jobs.c.id == str(live.id))
                .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )

        reaped = queue.reap_orphaned_leases()
        assert [r.id for r in reaped] == [job.id], "the reaper touched a re-claimable job"
        assert reaped[0].state is IngestionJobState.DEAD_LETTER
        assert reaped[0].error_code == "orphaned_lease"
        # The re-claimable job is untouched and can still be picked up.
        assert queue.claim("worker-3", lease_seconds=5).id == live.id
        # Idempotent: a second reap finds nothing.
        assert queue.reap_orphaned_leases() == []
    finally:
        repo.close()


def test_a_transient_object_store_error_becomes_a_typed_retryable_failure() -> None:
    """A botocore transport error must not escape the store as an unknown exception — it
    would crash the worker and 500 the API. Translated to ObjectStoreUnavailable, it is
    retryable for the worker and a 503 for the reader."""

    from korpus.infrastructure.object_store import S3ObjectStore

    class _Boto(Exception):
        pass

    _Boto.__module__ = "botocore.exceptions"

    class _Client:
        def head_object(self, **kwargs):
            raise _Boto("EndpointConnectionError")

    store = S3ObjectStore(bucket="korpus", prefix="", client=_Client())
    with pytest.raises(ObjectStoreUnavailable):
        store.exists("00/00/" + "a" * 64)


def test_a_caller_error_is_not_disguised_as_an_outage() -> None:
    """The translation must leave ValueError alone: a bad object key is the caller's fault
    and must not be retried as if the store were down."""
    from korpus.infrastructure.object_store import S3ObjectStore

    store = S3ObjectStore(bucket="korpus", prefix="objects", client=object())
    with pytest.raises(ValueError):
        store.get("not-a-valid-key")
