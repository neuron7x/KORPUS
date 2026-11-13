from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from korpus.infrastructure.migration_admission import MigrationAdmissionError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[3]
HEAD = "0025_sealed_provenance_integrity"
BASE = "0024_capability_effect_ledger"
pytestmark = pytest.mark.postgres


@pytest.fixture
def admission_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[URL, Config]]:
    raw = os.getenv("KORPUS_TEST_DATABASE_ADMIN_URL")
    if not raw:
        if os.getenv("KORPUS_TEST_DATABASE_URL") or os.getenv("KORPUS_POSTGRES_TEST_URL"):
            pytest.fail("PostgreSQL admission requires the actual admin database URL")
        pytest.skip("PostgreSQL-only controls execute in the required postgres-full-suite")
    admin = create_engine(raw, isolation_level="AUTOCOMMIT")
    name = "korpus_admission_" + uuid.uuid4().hex
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    url = make_url(raw).set(database=name)
    config = Config(str(ROOT / "apps/api/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "apps/api/migrations"))
    monkeypatch.setenv("KORPUS_DATABASE_URL", url.render_as_string(hide_password=False))
    try:
        yield url, config
    finally:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}"')
        admin.dispose()


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE SCHEMA foreign_state",
        "CREATE SCHEMA pgx; CREATE TABLE pgx.sentinel(value integer)",
        "CREATE TYPE marker AS ENUM ('a', 'b')",
        "CREATE FUNCTION marker() RETURNS int LANGUAGE SQL AS 'SELECT 1'",
        "CREATE TABLE sentinel(value text)",
    ],
    ids=["schema", "literal-prefix", "type", "function", "table"],
)
def test_nonempty_postgres_catalog_cannot_claim_bootstrap(
    admission_database: tuple[URL, Config], ddl: str
) -> None:
    url, config = admission_database
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(ddl)
        with pytest.raises(MigrationAdmissionError, match="DENIED_RETIREMENT_UNPROVEN"):
            command.upgrade(config, "head")
        assert not inspect(engine).has_table("alembic_version", schema="public")
        assert not inspect(engine).has_table("documents", schema="public")
    finally:
        engine.dispose()


def test_postgres_baseline_forward_does_not_authorize_contract_upgrade(
    admission_database: tuple[URL, Config],
) -> None:
    url, config = admission_database
    command.upgrade(config, "0023_evidence_search_vector")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE sentinel(value text)")
            connection.exec_driver_sql("INSERT INTO sentinel VALUES ('preserve')")
        command.upgrade(config, BASE)
        before = inspect(engine).get_table_names(schema="public")
        with pytest.raises(MigrationAdmissionError, match="DENIED_RETIREMENT_UNPROVEN"):
            command.upgrade(config, "head")
        assert inspect(engine).get_table_names(schema="public") == before
        with engine.connect() as connection:
            assert connection.execute(text("SELECT value FROM sentinel")).all() == [("preserve",)]
            assert connection.execute(text("SELECT version_num FROM alembic_version")).all() == [
                (BASE,)
            ]
    finally:
        engine.dispose()


def test_postgres_noop_requires_active_semantic_guards(
    admission_database: tuple[URL, Config],
) -> None:
    url, config = admission_database
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE documents DISABLE TRIGGER trg_sealed_document_delete"
            )
        with pytest.raises(MigrationAdmissionError, match="DENIED_CURRENT_STATE_UNPROVEN"):
            command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).all() == [
                (HEAD,)
            ]
    finally:
        engine.dispose()
