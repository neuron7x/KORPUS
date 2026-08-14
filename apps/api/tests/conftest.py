from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity
from korpus.main import create_app
from korpus.security.auth import get_identity


class IdentityProvider:
    def __init__(self, identity: Identity) -> None:
        self.current = identity

    def __call__(self) -> Identity:
        return self.current


@pytest.fixture
def admin_identity() -> Identity:
    return Identity(
        subject="admin-test",
        roles=frozenset({"admin", "curator", "reviewer", "user", "auditor"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public", "training", "restricted-demo"}),
    )


@pytest.fixture
def public_identity() -> Identity:
    return Identity(
        subject="public-test",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
    )


@pytest.fixture
def authenticated_identity() -> Identity:
    return Identity(
        subject="authenticated-test",
        roles=frozenset({"user"}),
        clearance=AccessTier.AUTHENTICATED,
        corpora=frozenset({"public", "training"}),
    )


#: Point this at a migrated PostgreSQL database to run the whole suite against it.
#: Every closure in this tree was proved on SQLite; the admission boundary names that
#: as its own debt, because the two dialects have separate implementations of the
#: currency filters, the integrity check and the retrieval projection. With the
#: variable set the suite reuses one migrated database and truncates between tests,
#: so the schema under test is the one the migrations produce rather than the one
#: `metadata.create_all` would.
POSTGRES_SUITE_URL = os.getenv("KORPUS_TEST_DATABASE_URL")
#: Truncation needs privileges the application role must not have, so the reset runs
#: as the owner while the suite itself connects as the least-privilege app role —
#: the same split the deployment uses.
POSTGRES_ADMIN_URL = os.getenv("KORPUS_TEST_DATABASE_ADMIN_URL") or POSTGRES_SUITE_URL


def _reset_postgres(url: str) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(url, future=True)
    try:
        with engine.begin() as connection:
            names = [
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                        "AND tablename <> 'alembic_version'"
                    )
                )
            ]
            if names:
                quoted = ", ".join(f'public."{name}"' for name in names)
                connection.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
            # Migrations seed both singleton roots. Truncation removes them, and startup
            # deliberately refuses a migrated database whose audit or corpus timeline
            # has no origin. Restore only those roots; every product row remains empty.
            connection.execute(
                text(
                    "INSERT INTO audit_heads (singleton_id, sequence, head_hash) "
                    "VALUES (1, 0, :zero) ON CONFLICT (singleton_id) DO NOTHING"
                ),
                {"zero": "0" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO corpus_state_epoch (singleton_id, epoch) VALUES (1, 0) "
                    "ON CONFLICT (singleton_id) DO NOTHING"
                )
            )
    finally:
        engine.dispose()


def reset_database() -> None:
    """Empty the PostgreSQL suite database, or do nothing on SQLite.

    Exposed for the tests that build their own repository rather than taking the
    `client` fixture: they share the database when the whole suite runs on PostgreSQL.
    """

    if POSTGRES_SUITE_URL:
        _reset_postgres(POSTGRES_ADMIN_URL or POSTGRES_SUITE_URL)


@pytest.fixture
def client(tmp_path: Path, admin_identity: Identity) -> Iterator[TestClient]:
    if POSTGRES_SUITE_URL:
        _reset_postgres(POSTGRES_ADMIN_URL or POSTGRES_SUITE_URL)
        database_url = POSTGRES_SUITE_URL
    else:
        database_url = f"sqlite:///{tmp_path / 'test.db'}"
    settings = Settings(
        environment="test",
        # On PostgreSQL the schema comes from the migrations and the app role is not
        # its owner, which is the deployment posture: `auto` would try to create the
        # search index and be refused. This is also the only configuration in which
        # the start-up revision check runs at all.
        schema_mode="migrations" if POSTGRES_SUITE_URL else "auto",
        database_url=database_url,
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "audit-anchor.json",
        audit_hmac_key="test-audit-key",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        min_retrieval_score=0.08,
        min_query_coverage=0.15,
        min_support_score=0.08,
        max_upload_bytes=1024 * 1024,
    )
    app = create_app(settings)
    provider = IdentityProvider(admin_identity)
    app.dependency_overrides[get_identity] = provider
    with TestClient(app) as test_client:
        test_client.identity_provider = provider  # type: ignore[attr-defined]
        yield test_client


def set_identity(client: TestClient, identity: Identity) -> None:
    client.identity_provider.current = identity  # type: ignore[attr-defined]


@contextmanager
def privileged_connection(client: TestClient) -> Iterator[Any]:
    """A connection that can write rows the application would never write.

    Several properties are only reachable from a state the API refuses to produce — a
    supersession edge that crosses documents, a version with no lower bound, a tampered
    audit row. On SQLite any connection can write them. On PostgreSQL the application
    role is deliberately unable to: row-level security gates the writes it is allowed
    to make, and `audit_events` carries no UPDATE or DELETE grant at all. Both of those
    are the deployment behaving correctly, and both would otherwise turn "the check
    holds" into "the test could not run" — silently, since a refused UPDATE affects
    zero rows without raising.

    So the fixture connects as the owner when a PostgreSQL admin URL is configured, and
    the tests that use it are testing the layer above, not the grants. The grants get
    their own test.
    """

    if POSTGRES_SUITE_URL and POSTGRES_ADMIN_URL and POSTGRES_ADMIN_URL != POSTGRES_SUITE_URL:
        from sqlalchemy import create_engine

        engine = create_engine(POSTGRES_ADMIN_URL, future=True)
        try:
            with engine.begin() as connection:
                yield connection
        finally:
            engine.dispose()
        return
    with client.app.state.repository.engine.begin() as connection:
        yield connection
