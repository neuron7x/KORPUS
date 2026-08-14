from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from apps.api.tests.conftest import POSTGRES_ADMIN_URL, reset_database
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.rls_identity import RlsIdentityBinder

APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL") or os.getenv("KORPUS_TEST_DATABASE_URL")
REVIEW_URL = os.getenv("KORPUS_REVIEW_DATABASE_URL")
IDENTITY_URL = os.getenv("RLS_IDENTITY_DATABASE_URL")
pytestmark = pytest.mark.postgres

LOW = Identity(
    subject="rls-dml-low",
    roles=frozenset({"user"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public-corpus"}),
)


def _require_boundary() -> None:
    if not APP_URL or not REVIEW_URL or not IDENTITY_URL or not POSTGRES_ADMIN_URL:
        pytest.skip("split PostgreSQL app/review/identity URLs are required")


def _engine(url: str):
    return create_engine(url, future=True, pool_pre_ping=True)


def _binder() -> RlsIdentityBinder:
    assert APP_URL and REVIEW_URL and IDENTITY_URL
    return RlsIdentityBinder(
        APP_URL,
        IDENTITY_URL,
        {"future": True, "pool_pre_ping": True},
        review_database_url=REVIEW_URL,
    )


def _insert_admin_document(connection, document_id: str, title: str) -> None:
    connection.execute(
        text(
            "INSERT INTO documents("
            "id,canonical_title,corpus_id,issuer,jurisdiction,document_type,"
            "access_tier,classification,compartments_json,created_at"
            ") VALUES ("
            ":id,:title,'public-corpus','issuer','UA','reference',"
            "0,'public','[]',statement_timestamp())"
        ),
        {"id": document_id, "title": title},
    )


def _forge_roles(connection) -> None:
    connection.execute(
        text("SELECT pg_catalog.set_config('korpus.roles','admin,curator',true)")
    )


def test_forged_legacy_roles_cannot_update_delete_or_insert() -> None:
    _require_boundary()
    reset_database()
    assert APP_URL and POSTGRES_ADMIN_URL
    existing = "00000000-0000-0000-0000-000000000201"
    injected = "00000000-0000-0000-0000-000000000202"
    admin = _engine(POSTGRES_ADMIN_URL)
    app = _engine(APP_URL)
    binder = _binder()
    try:
        with admin.begin() as connection:
            _insert_admin_document(connection, existing, "protected")

        with app.begin() as connection:
            binder.bind(connection, LOW)
            _forge_roles(connection)
            assert connection.execute(
                text("SELECT public.korpus_rls_roles()")
            ).scalar_one() == ["user"]
            update_result = connection.execute(
                text("UPDATE documents SET canonical_title='forged' WHERE id=:id"),
                {"id": existing},
            )
            delete_result = connection.execute(
                text("DELETE FROM documents WHERE id=:id"),
                {"id": existing},
            )
            assert update_result.rowcount == 0
            assert delete_result.rowcount == 0

        with pytest.raises(DBAPIError), app.begin() as connection:
            binder.bind(connection, LOW)
            _forge_roles(connection)
            connection.execute(
                text(
                    "INSERT INTO documents("
                    "id,canonical_title,corpus_id,issuer,jurisdiction,document_type,"
                    "access_tier,classification,compartments_json,created_at"
                    ") VALUES ("
                    ":id,'forged-insert','public-corpus','issuer','UA','reference',"
                    "0,'public','[]',statement_timestamp())"
                ),
                {"id": injected},
            )

        with admin.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT id,canonical_title FROM documents "
                    "WHERE id IN (:existing,:injected) ORDER BY id"
                ),
                {"existing": existing, "injected": injected},
            ).all()
        assert rows == [(existing, "protected")]
    finally:
        binder.close()
        app.dispose()
        admin.dispose()
