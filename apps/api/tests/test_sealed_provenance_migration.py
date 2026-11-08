"""SQLite destruction controls for the real seal-guard migration.

A SQLite OR REPLACE can bypass DELETE triggers when recursive_triggers=OFF.
Exercise that path against the migration itself, not a copied trigger oracle.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event
from sqlalchemy.exc import DBAPIError

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "migrations/versions/0025_sealed_provenance_integrity.py"
)
_MUTANTS = (
    ("sealed-document-delete", "DELETE FROM documents WHERE id='a'", False),
    ("sealed-version-delete", "DELETE FROM document_versions WHERE id='a1'", False),
    (
        "sealed-source-update",
        "UPDATE document_versions SET source_hash='changed' WHERE id='a1'",
        False,
    ),
    (
        "sealed-reparent",
        "UPDATE document_versions SET document_id='c' WHERE id='a1'",
        False,
    ),
    ("document-replace", "INSERT OR REPLACE INTO documents VALUES ('a','replacement')", False),
    (
        "version-id-replace",
        "INSERT OR REPLACE INTO document_versions VALUES ('a1','a','1',NULL,'x','y','z','zz',1)",
        False,
    ),
    (
        "version-unique-replace",
        "INSERT OR REPLACE INTO document_versions VALUES ('new','a','1',NULL,'x','y','z','zz',0)",
        False,
    ),
    (
        "update-replace-revision",
        "UPDATE OR REPLACE document_versions SET document_id='a',revision='1' WHERE id='b1'",
        False,
    ),
    (
        "update-replace-version-id",
        "UPDATE OR REPLACE document_versions SET id='a1' WHERE id='b1'",
        False,
    ),
    ("update-replace-document-id", "UPDATE OR REPLACE documents SET id='a' WHERE id='b'", False),
    (
        "draft-provenance-positive",
        "UPDATE document_versions SET source_hash='changed' WHERE id='b1'",
        True,
    ),
    ("draft-delete-positive", "DELETE FROM document_versions WHERE id='b1'", True),
)


@pytest.mark.parametrize(("case", "statement", "allowed"), _MUTANTS, ids=[x[0] for x in _MUTANTS])
def test_sqlite_seal_guards_reject_destruction_but_allow_drafts(
    case: str, statement: str, allowed: bool
) -> None:
    spec = importlib.util.spec_from_file_location("korpus_migration_0025", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")  # type: ignore[attr-defined]
        dbapi_connection.execute("PRAGMA recursive_triggers=OFF")  # type: ignore[attr-defined]

    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE documents(id TEXT PRIMARY KEY, name TEXT)")
            connection.exec_driver_sql(
                "CREATE TABLE document_versions("
                "id TEXT PRIMARY KEY, document_id TEXT REFERENCES documents(id) "
                "ON DELETE CASCADE, "
                "revision TEXT NOT NULL, evidence_digest TEXT, source_hash TEXT, "
                "object_key TEXT, authority TEXT, source_uri TEXT, is_current INT, "
                "UNIQUE(document_id,revision))"
            )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX current_unique ON document_versions(document_id) "
                "WHERE is_current=1"
            )
            connection.exec_driver_sql(
                "CREATE TABLE evidence_spans(id TEXT PRIMARY KEY, "
                "version_id TEXT REFERENCES document_versions(id) ON DELETE CASCADE)"
            )
            connection.exec_driver_sql(
                "INSERT INTO documents VALUES ('a','sealed'),('b','draft'),('c','carrier')"
            )
            connection.exec_driver_sql(
                "INSERT INTO document_versions VALUES "
                "('a1','a','1','sealed','a','obj','off','uri',1),"
                "('b1','b','1',NULL,'b','obj','off','uri',0)"
            )
            connection.exec_driver_sql("INSERT INTO evidence_spans VALUES ('span-a','a1')")
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            if allowed:
                with connection.begin_nested() as savepoint:
                    connection.exec_driver_sql(statement)
                    savepoint.rollback()
            else:
                with pytest.raises(DBAPIError, match="sealed"), connection.begin_nested():
                    connection.exec_driver_sql(statement)
            assert (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM document_versions WHERE id='a1'"
                ).scalar_one()
                == 1
            ), case
            assert (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM evidence_spans WHERE id='span-a'"
                ).scalar_one()
                == 1
            ), case
    finally:
        engine.dispose()
