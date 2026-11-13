"""The real auto-schema path must enforce the migrated sealed-evidence boundary."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    ReviewState,
)
from korpus.infrastructure.corpus_snapshot import SqlCorpusSnapshotReader
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.schema import documents, versions
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from apps.api.tests.conftest import privileged_connection


@pytest.fixture(params=("auto", "migration"))
def sealed_runtime(
    tmp_path: Path, request
) -> Iterator[tuple[SqlRepository, SqlCorpusSnapshotReader]]:
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'seal.sqlite'}",
        "synthetic-audit-key",
        audit_anchor_path=tmp_path / "anchor.json",
    )
    try:
        repository.initialize(create_schema=True)
        reader = SqlCorpusSnapshotReader(repository)
        reader.initialize(create_schema=True)
        if request.param == "migration":
            path = (
                Path(__file__).parents[1]
                / "migrations/versions/0025_sealed_provenance_integrity.py"
            )
            spec = importlib.util.spec_from_file_location("migration_0025_runtime", path)
            assert spec is not None and spec.loader is not None
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            with (
                repository.engine.begin() as connection,
                Operations.context(MigrationContext.configure(connection)),
            ):
                migration.downgrade()
                migration.upgrade()
        reader.initialize(create_schema=False)
        yield repository, reader
    finally:
        repository.close()


def _bundle(repository: SqlRepository, *, sealed: bool) -> tuple[str, str, str]:
    actor = Identity(
        subject="guard-test",
        roles=frozenset({"admin", "user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
    )
    document = DocumentRecord(
        canonical_title="Synthetic guard control",
        corpus_id="public",
        issuer="synthetic",
        jurisdiction="UA",
        document_type="test",
        access_tier=AccessTier.PUBLIC,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1",
        source_hash="a" * 64,
        object_key="synthetic",
        mime_type="text/plain",
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.APPROVED if sealed else ReviewState.QUARANTINED,
        publication_date=date(2020, 1, 1),
        is_current=sealed,
    )
    span = EvidenceSpanRecord(version_id=version.id, ordinal=0, text="Synthetic evidence")
    repository.create_document_bundle(actor, document, version, [span], {"synthetic": True})
    return str(document.id), str(version.id), str(span.id)


@pytest.mark.parametrize(
    "operation",
    (
        "document-delete",
        "version-delete",
        "provenance",
        "reparent",
        "replace-document",
        "replace-version",
    ),
)
@pytest.mark.parametrize("review_state", ("approved", "rejected"))
def test_runtime_seal_survives_parent_and_provenance_destruction(
    sealed_runtime, operation: str, review_state: str
) -> None:
    repository, reader = sealed_runtime
    document_id, version_id, span_id = _bundle(repository, sealed=True)
    other_document_id, _, _ = _bundle(repository, sealed=False)
    with repository.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE document_versions SET review_state=:state, is_current=:current WHERE id=:id"
            ),
            {"state": review_state, "current": review_state == "approved", "id": version_id},
        )
        assert connection.execute(
            text("SELECT evidence_digest FROM document_versions WHERE id=:id"), {"id": version_id}
        ).scalar_one()
        statements = {
            "document-delete": (text("DELETE FROM documents WHERE id=:id"), {"id": document_id}),
            "version-delete": (
                text("DELETE FROM document_versions WHERE id=:id"),
                {"id": version_id},
            ),
            "provenance": (
                text("UPDATE document_versions SET source_hash='changed' WHERE id=:id"),
                {"id": version_id},
            ),
            "reparent": (
                text("UPDATE document_versions SET document_id=:parent WHERE id=:id"),
                {"parent": other_document_id, "id": version_id},
            ),
        }
        if operation.startswith("replace-"):
            table = documents if operation == "replace-document" else versions
            identity = document_id if table is documents else version_id
            row = dict(
                connection.execute(select(table).where(table.c.id == identity)).mappings().one()
            )
            statement, params = table.insert().prefix_with("OR REPLACE").values(**row), {}
        else:
            statement, params = statements[operation]
        with pytest.raises(DBAPIError, match="sealed"), connection.begin_nested():
            connection.execute(statement, params)
        assert (
            connection.execute(
                text("SELECT count(*) FROM evidence_spans WHERE id=:id"), {"id": span_id}
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                text("SELECT source_hash FROM document_versions WHERE id=:id"), {"id": version_id}
            ).scalar_one()
            == "a" * 64
        )
    reader.initialize(create_schema=False)


def test_runtime_draft_updates_and_parent_deletion_remain_allowed(sealed_runtime) -> None:
    repository, _ = sealed_runtime
    document_id, version_id, span_id = _bundle(repository, sealed=False)
    with repository.engine.begin() as connection:
        changed = connection.execute(
            text("UPDATE document_versions SET source_hash='changed' WHERE id=:id"),
            {"id": version_id},
        )
        assert changed.rowcount == 1
        deleted = connection.execute(
            text("DELETE FROM documents WHERE id=:id"), {"id": document_id}
        )
        assert deleted.rowcount == 1
        assert (
            connection.execute(
                text("SELECT count(*) FROM evidence_spans WHERE id=:id"), {"id": span_id}
            ).scalar_one()
            == 0
        )


def test_auto_guard_installation_is_idempotent_and_matches_migrated_contract(client) -> None:
    reader = client.app.state.corpus_snapshot_reader
    with privileged_connection(client) as connection:
        savepoint = connection.begin_nested()
        try:
            reader._install_guards(connection)
            reader._require_guards(connection)
            reader._install_guards(connection)
            reader._require_guards(connection)
        finally:
            savepoint.rollback()


@pytest.mark.parametrize(
    ("table", "name"),
    (
        ("documents", "trg_sealed_document_delete"),
        ("document_versions", "trg_sealed_version_delete"),
        ("document_versions", "trg_sealed_version_provenance_update"),
    ),
)
@pytest.mark.parametrize("intervention", ("missing", "inert"))
def test_startup_refuses_missing_or_inert_sealed_guard(
    client, table: str, name: str, intervention: str
) -> None:
    reader = client.app.state.corpus_snapshot_reader
    with privileged_connection(client) as connection:
        savepoint = connection.begin_nested()
        try:
            suffix = f" ON {table}" if connection.dialect.name == "postgresql" else ""
            connection.execute(text(f"DROP TRIGGER {name}{suffix}"))
            if intervention == "inert":
                if connection.dialect.name == "sqlite":
                    connection.execute(
                        text(f"CREATE TRIGGER {name} BEFORE DELETE ON {table} BEGIN SELECT 1; END")
                    )
                else:
                    connection.execute(
                        text(
                            f"CREATE TRIGGER {name} BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION korpus_bump_corpus_state_epoch()"
                        )
                    )
            with pytest.raises(RuntimeError, match="corpus snapshot guard"):
                reader._require_guards(connection)
        finally:
            savepoint.rollback()
    reader.initialize(create_schema=False)


@pytest.mark.parametrize("guard", ("parent_delete", "provenance_update"))
def test_startup_refuses_same_function_or_trigger_identity_with_inert_body(
    client, guard: str
) -> None:
    reader = client.app.state.corpus_snapshot_reader
    with privileged_connection(client) as connection:
        savepoint = connection.begin_nested()
        try:
            if connection.dialect.name == "postgresql":
                security = "SECURITY DEFINER" if guard == "parent_delete" else ""
                returned = "OLD" if guard == "parent_delete" else "NEW"
                connection.execute(
                    text(
                        f"CREATE OR REPLACE FUNCTION public.korpus_guard_sealed_{guard}() "
                        f"RETURNS trigger AS $$ BEGIN RETURN {returned}; END; $$ "
                        f"LANGUAGE plpgsql {security} SET search_path = pg_catalog, public"
                    )
                )
            else:
                name = (
                    "trg_sealed_document_delete"
                    if guard == "parent_delete"
                    else "trg_sealed_version_provenance_update"
                )
                actual = connection.execute(
                    text("SELECT sql FROM sqlite_master WHERE name=:name"), {"name": name}
                ).scalar_one()
                connection.execute(text(f"DROP TRIGGER {name}"))
                connection.execute(text(actual.replace("WHEN ", "WHEN 0 AND ", 1)))
            with pytest.raises(RuntimeError, match=r"invalid (definition|function body)"):
                reader._require_guards(connection)
        finally:
            savepoint.rollback()
    reader.initialize(create_schema=False)
