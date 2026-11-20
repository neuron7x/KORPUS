"""Composition and fail-closed binding checks; native RLS proof lives in PostgreSQL tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from korpus import cli, main
from korpus.config import Settings
from korpus.domain.models import Identity
from korpus.infrastructure.ingestion_jobs import SqlIngestionJobQueue
from korpus.infrastructure.repository import SqlRepository
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection


@pytest.fixture
def composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Settings, SqlRepository, list[Identity]]]:
    # These composition checks own SQLite state even inside the hosted PG suite.
    # Never consume or reset the caller's database, model credentials or object store.
    for key in tuple(os.environ):
        if key.startswith("KORPUS_"):
            monkeypatch.delenv(key)
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'composition.db'}",
        object_root=tmp_path / "objects",
        quarantine_object_root=tmp_path / "quarantine",
        audit_anchor_path=tmp_path / "anchor.json",
        audit_hmac_key="queue-composition-audit-key",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        ingestion_mode="durable_async",
    )
    repository = SqlRepository(
        settings.database_url,
        settings.audit_hmac_key,
        audit_anchor_path=settings.audit_anchor_path,
    )
    bound: list[Identity] = []

    def bind(connection: Connection, identity: Identity) -> None:
        assert connection.in_transaction(), "identity must bind the queue transaction"
        bound.append(identity)

    monkeypatch.setattr(repository, "_apply_postgres_identity", bind)
    try:
        yield settings, repository, bound
    finally:
        repository.close()


def test_postgres_queue_refuses_missing_broker_before_connecting() -> None:
    engine = create_engine("postgresql+psycopg://unbound@invalid.invalid/unused")
    try:
        with pytest.raises(ValueError, match="requires a trusted identity binder"):
            SqlIngestionJobQueue(engine)
    finally:
        engine.dispose()


def test_api_composition_passes_repository_binder(composition, monkeypatch) -> None:
    settings, repository, bound = composition
    monkeypatch.setattr(main, "create_repository", lambda *args: repository)
    reader = Identity(subject="api-queue-reader", roles=frozenset({"user"}))
    with TestClient(main.create_app(settings)) as client:
        assert client.app.state.ingestion_jobs.get(reader, uuid4()) is None
    assert reader in bound


def test_cli_worker_composition_passes_repository_binder(composition, monkeypatch, capsys) -> None:
    settings, repository, bound = composition
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "create_repository", lambda *args: repository)
    monkeypatch.setattr("sys.argv", ["korpus", "worker-once", "--worker-id", "bound-cli-worker"])
    cli.main()
    assert "no queued job" in capsys.readouterr().out
    assert any(
        identity.subject == "bound-cli-worker" and identity.roles == frozenset({"worker"})
        for identity in bound
    )


def test_broker_failure_propagates_without_an_unbound_fallback(composition) -> None:
    _, repository, _ = composition
    repository.initialize()

    def unavailable(connection: Connection, identity: Identity) -> None:
        raise RuntimeError("authorization broker unavailable")

    statements: list[str] = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    queue = SqlIngestionJobQueue(repository.engine, bind_identity=unavailable)
    event.listen(repository.engine, "before_cursor_execute", record)
    try:
        with pytest.raises(RuntimeError, match="authorization broker unavailable"):
            queue.get(Identity(subject="reader", roles=frozenset({"user"})), uuid4())
    finally:
        event.remove(repository.engine, "before_cursor_execute", record)
    assert statements == [], "a failed binding must prevent queue SQL"
