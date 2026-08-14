from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text, update
from sqlalchemy.exc import DBAPIError

from apps.api.tests.conftest import POSTGRES_ADMIN_URL, reset_database
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.corpus_snapshot import SqlCorpusSnapshotReader
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.schema import corpus_state_epoch

POSTGRES_URL = os.getenv("KORPUS_POSTGRES_TEST_URL") or os.getenv("KORPUS_TEST_DATABASE_URL")
pytestmark = pytest.mark.postgres


@pytest.mark.skipif(not POSTGRES_URL, reason="PostgreSQL test URL is not configured")
def test_postgres_application_role_cannot_forge_corpus_state_epoch(tmp_path: Path) -> None:
    """The monotonic epoch is observable to the app but not writable by it."""
    reset_database()
    repository = SqlRepository(
        POSTGRES_URL,
        "postgres-temporal-privilege-key",
        audit_anchor_path=tmp_path / "postgres-temporal-privilege-anchor.json",
    )
    repository.initialize(create_schema=False)
    actor = Identity(
        subject="postgres-temporal-admin",
        roles=frozenset({"admin", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )

    try:
        with pytest.raises(DBAPIError), repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, actor)
            connection.execute(
                update(corpus_state_epoch)
                .where(corpus_state_epoch.c.singleton_id == 1)
                .values(epoch=corpus_state_epoch.c.epoch + 1000)
            )
    finally:
        repository.close()


@pytest.mark.skipif(
    not POSTGRES_URL or not POSTGRES_ADMIN_URL or POSTGRES_ADMIN_URL == POSTGRES_URL,
    reason="separate PostgreSQL owner URL is required to tamper with a guard function",
)
def test_postgres_startup_rejects_correctly_named_inert_epoch_function(tmp_path: Path) -> None:
    """Function name, SECURITY DEFINER and search_path are insufficient evidence."""
    reset_database()
    admin_engine = create_engine(POSTGRES_ADMIN_URL, future=True)
    repository = SqlRepository(
        POSTGRES_URL,
        "postgres-temporal-function-guard-key",
        audit_anchor_path=tmp_path / "postgres-temporal-function-guard-anchor.json",
    )
    repository.initialize(create_schema=False)

    with admin_engine.begin() as connection:
        original = connection.execute(
            text(
                "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'public' "
                "AND p.proname = 'korpus_bump_corpus_state_epoch'"
            )
        ).scalar_one()
        connection.exec_driver_sql(
            """
            CREATE OR REPLACE FUNCTION korpus_bump_corpus_state_epoch() RETURNS trigger AS $$
            BEGIN
              RETURN NULL;
            END;
            $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
            """
        )

    try:
        reader = SqlCorpusSnapshotReader(repository)
        with pytest.raises(RuntimeError, match="korpus_bump_corpus_state_epoch.*invalid function body"):
            reader.initialize(create_schema=False)
    finally:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(str(original))
        repository.close()
        admin_engine.dispose()
