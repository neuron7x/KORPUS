"""The migration, run rather than read.

ACT-001 Workstream I. Two paths a deployment can take, and both are exercised against a
real SQLite database driven by alembic:

  clean bootstrap   nothing, then head. What a new deployment does.
  upgrade           0011 — the v6.0.0 head — then 0012. What the running deployment does,
                    with corpus rows already in the tables the migration must not touch.

The second carries the property that matters. A migration that dropped or rewrote a
document version would take five hours of import with it, and the way that gets shipped is
that nobody ran the upgrade against a database with rows in it.

The downgrade is exercised too. A migration that cannot be reversed cannot be rehearsed,
and rehearsing it is how anyone learns the cost before paying it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "apps/api"

TENANCY_TABLES = {
    "accounts",
    "plans",
    "subscriptions",
    "billing_events",
    "conversations",
    "messages",
}


def _alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=API,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(API / "src"),
            "KORPUS_DATABASE_URL": database_url,
            "KORPUS_AUDIT_HMAC_KEY": "migration-test-key",
        },
    )


def _run(database_url: str, *arguments: str) -> None:
    completed = _alembic(database_url, *arguments)
    assert completed.returncode == 0, completed.stderr[-4000:]


def test_a_clean_database_migrates_to_the_pinned_head(tmp_path: Path) -> None:
    database = tmp_path / "bootstrap.db"
    url = f"sqlite:///{database}"
    _run(url, "upgrade", "head")

    engine = create_engine(url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
        assert tables >= TENANCY_TABLES, sorted(TENANCY_TABLES - tables)
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()

    from korpus.infrastructure.schema import SCHEMA_REVISION

    assert revision == SCHEMA_REVISION, (
        "the code's pinned revision and the migration head disagree; a migrated "
        "PostgreSQL deployment would refuse to start"
    )


def test_upgrading_from_the_previous_release_preserves_the_corpus(tmp_path: Path) -> None:
    """The one that would cost five hours of import if it were wrong."""
    database = tmp_path / "upgrade.db"
    url = f"sqlite:///{database}"
    _run(url, "upgrade", "0011_audit_key_id")

    engine = create_engine(url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO documents (id, canonical_title, corpus_id, issuer, "
                    "jurisdiction, document_type, access_tier, classification, "
                    "compartments_json, created_at) VALUES ('d1', 'Настанова', 'public', "
                    "'Ministry', 'UA', 'order', 0, 'public', '[]', '2026-01-01T00:00:00Z')"
                )
            )
        before = set(inspect(engine).get_table_names())
        assert not (TENANCY_TABLES & before), "0011 already carries the tenancy tables"

        _run(url, "upgrade", "head")

        after = set(inspect(engine).get_table_names())
        assert after >= TENANCY_TABLES
        with engine.connect() as connection:
            titles = (
                connection.execute(text("SELECT canonical_title FROM documents")).scalars().all()
            )
        assert titles == ["Настанова"], "the upgrade disturbed the corpus"
    finally:
        engine.dispose()


def test_the_upgrade_can_be_reversed(tmp_path: Path) -> None:
    database = tmp_path / "rollback.db"
    url = f"sqlite:///{database}"
    _run(url, "upgrade", "head")
    _run(url, "downgrade", "0011_audit_key_id")

    engine = create_engine(url, future=True)
    try:
        remaining = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert not (TENANCY_TABLES & remaining), sorted(TENANCY_TABLES & remaining)


def test_the_unique_constraints_are_enforced_by_the_migrated_schema(tmp_path: Path) -> None:
    """Not by `metadata.create_all` — by what alembic actually builds.

    The two are separate code paths and have disagreed before. A uniqueness rule that
    exists only in the SQLAlchemy metadata is a rule the production database does not
    have.
    """
    database = tmp_path / "constraints.db"
    url = f"sqlite:///{database}"
    _run(url, "upgrade", "head")

    engine = create_engine(url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO accounts (id, auth_subject, status, created_at, updated_at) "
                    "VALUES ('a1', 'oidc|one', 'active', '2026-01-01', '2026-01-01')"
                )
            )
        with pytest.raises(Exception, match=r"UNIQUE|unique"), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO accounts (id, auth_subject, status, created_at, updated_at) "
                    "VALUES ('a2', 'oidc|one', 'active', '2026-01-01', '2026-01-01')"
                )
            )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO billing_events (id, provider, provider_event_id, event_type, "
                    "payload_hash, received_at) VALUES ('e1', 'p', 'evt', 't', '"
                    + "0" * 64
                    + "', '2026-01-01')"
                )
            )
        with pytest.raises(Exception, match=r"UNIQUE|unique"), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO billing_events (id, provider, provider_event_id, event_type, "
                    "payload_hash, received_at) VALUES ('e2', 'p', 'evt', 't', '"
                    + "0" * 64
                    + "', '2026-01-01')"
                )
            )
    finally:
        engine.dispose()


def test_a_disabled_account_without_a_timestamp_is_refused_by_the_database(
    tmp_path: Path,
) -> None:
    """The check constraint, from the migrated schema. "Since when" must be answerable."""
    database = tmp_path / "checks.db"
    url = f"sqlite:///{database}"
    _run(url, "upgrade", "head")

    engine = create_engine(url, future=True)
    try:
        with pytest.raises(Exception, match=r"CHECK|constraint"), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO accounts (id, auth_subject, status, created_at, updated_at) "
                    "VALUES ('a1', 'oidc|x', 'disabled', '2026-01-01', '2026-01-01')"
                )
            )
    finally:
        engine.dispose()
