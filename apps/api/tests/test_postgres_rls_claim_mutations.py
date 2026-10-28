"""Prove caller-owned SQL settings cannot rewrite broker-bound RLS identity.

These are actual PostgreSQL destruction tests, not mock-only policy assertions.
They must run with korpus_app (non-superuser) and a separately authenticated
korpus_authz broker. A successful unauthorized query or write is a hard failure.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.rls_repository import RlsBoundSqlRepository
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from apps.api.tests.conftest import reset_database

APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL")
ADMIN_URL = os.getenv("KORPUS_TEST_DATABASE_ADMIN_URL")
AUTHZ_URL = os.getenv("KORPUS_AUTHZ_DATABASE_URL")
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not all((APP_URL, ADMIN_URL, AUTHZ_URL)),
        reason="real app/admin/authz PostgreSQL identities required",
    ),
]

GUC_ATTACKS = (
    ("clearance", "3"),
    ("corpora", "public,restricted-demo"),
    ("classifications", "public,internal,restricted"),
    ("compartments", "need-to-know"),
    ("roles", "user,admin"),
)


def _subject(*, privileged: bool = False) -> Identity:
    return Identity(
        subject="officer" if privileged else "ordinary-reader",
        roles=frozenset({"user", "admin"} if privileged else {"user"}),
        clearance=AccessTier.RESTRICTED if privileged else AccessTier.PUBLIC,
        corpora=frozenset({"public", "restricted-demo"} if privileged else {"public"}),
        compartments=frozenset({"need-to-know"} if privileged else set()),
    )


def _seed(corpus: str, tier: int, classification: str) -> str:
    assert ADMIN_URL is not None
    document_id = str(uuid4())
    admin = create_engine(ADMIN_URL, future=True)
    try:
        with admin.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO documents("
                    "id, canonical_title, corpus_id, issuer, jurisdiction, "
                    "document_type, access_tier, classification, created_at, compartments_json"
                    ") VALUES (:id, :title, :corpus, 'Verifier', 'UA', 'order', "
                    ":tier, :classification, :now, '[]')"
                ),
                {
                    "id": document_id,
                    "title": "Original authoritative title",
                    "corpus": corpus,
                    "tier": tier,
                    "classification": classification,
                    "now": datetime.now(UTC),
                },
            )
    finally:
        admin.dispose()
    return document_id


def _repository() -> RlsBoundSqlRepository:
    assert APP_URL is not None and AUTHZ_URL is not None
    return RlsBoundSqlRepository(APP_URL, "test-only-audit-key", authz_database_url=AUTHZ_URL)


def _visible(connection, document_id: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT count(*) FROM documents WHERE id = :id"), {"id": document_id}
        ).scalar_one()
    )


def _forge_all(connection) -> None:
    for name, value in GUC_ATTACKS:
        connection.execute(
            text("SELECT set_config(:setting, :value, true)"),
            {"setting": f"korpus.{name}", "value": value},
        )


@pytest.mark.parametrize(("axis", "forged"), GUC_ATTACKS)
def test_each_app_owned_session_claim_is_ignored_by_broker(axis: str, forged: str) -> None:
    reset_database()
    public_id = _seed("public", 0, "public")
    restricted_id = _seed("restricted-demo", 3, "restricted")
    repository = _repository()
    try:
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, _subject())
            assert connection.execute(text("SELECT current_user")).scalar_one() == "korpus_app"
            assert _visible(connection, public_id)
            assert not _visible(connection, restricted_id)
            accessor = f"public.korpus_rls_{axis}()"
            before = connection.execute(text(f"SELECT {accessor}")).scalar_one()
            connection.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": f"korpus.{axis}", "value": forged},
            )
            after = connection.execute(text(f"SELECT {accessor}")).scalar_one()
            assert after == before, f"mutable session value replaced broker {axis}"
            assert _visible(connection, public_id)
            assert not _visible(connection, restricted_id)
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, _subject(privileged=True))
            assert _visible(connection, restricted_id), "always-deny is not a security proof"
    finally:
        repository.close()


@pytest.mark.parametrize("operation", ("UPDATE", "DELETE"))
def test_forged_claims_cannot_change_hidden_document(operation: str) -> None:
    reset_database()
    public_id = _seed("public", 0, "public")
    restricted_id = _seed("restricted-demo", 3, "restricted")
    repository = _repository()
    try:
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, _subject())
            assert _visible(connection, public_id)
            assert not _visible(connection, restricted_id)
            _forge_all(connection)
            sql = (
                "UPDATE documents SET canonical_title = 'forged-write' WHERE id = :id"
                if operation == "UPDATE"
                else "DELETE FROM documents WHERE id = :id"
            )
            result = connection.execute(text(sql), {"id": restricted_id})
            assert result.rowcount == 0, f"forged {operation} changed a hidden document"
        assert ADMIN_URL is not None
        admin = create_engine(ADMIN_URL, future=True)
        try:
            with admin.connect() as connection:
                title = connection.execute(
                    text("SELECT canonical_title FROM documents WHERE id = :id"),
                    {"id": restricted_id},
                ).scalar_one()
            assert title == "Original authoritative title"
        finally:
            admin.dispose()
    finally:
        repository.close()


def test_forged_claims_cannot_insert_a_restricted_document() -> None:
    reset_database()
    public_id = _seed("public", 0, "public")
    attempt = str(uuid4())
    repository = _repository()
    try:
        with pytest.raises(DBAPIError):
            with repository.engine.begin() as connection:
                repository._apply_postgres_identity(connection, _subject())
                assert _visible(connection, public_id)
                _forge_all(connection)
                connection.execute(
                    text(
                        "INSERT INTO documents("
                        "id, canonical_title, corpus_id, issuer, jurisdiction, "
                        "document_type, access_tier, classification, created_at, compartments_json"
                        ") VALUES (:id, 'forged-insert', 'restricted-demo', 'Verifier', "
                        "'UA', 'order', 3, 'restricted', :now, '[]')"
                    ),
                    {"id": attempt, "now": datetime.now(UTC)},
                )
        assert ADMIN_URL is not None
        admin = create_engine(ADMIN_URL, future=True)
        try:
            with admin.connect() as connection:
                assert not _visible(connection, attempt)
        finally:
            admin.dispose()
    finally:
        repository.close()
