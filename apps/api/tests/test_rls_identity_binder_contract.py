from __future__ import annotations

from types import SimpleNamespace

import pytest

from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.rls_identity import RlsIdentityBinder

PRIMARY = "postgresql+psycopg://korpus_app:app@db.internal:5432/korpus"
REVIEW = "postgresql+psycopg://korpus_review:review@db.internal:5432/korpus"


def test_postgres_identity_broker_is_mandatory() -> None:
    with pytest.raises(ValueError, match="broker URL is required"):
        RlsIdentityBinder(PRIMARY, None, {}, review_database_url=REVIEW)


def test_identity_broker_login_cannot_equal_app_login() -> None:
    same_login = "postgresql+psycopg://korpus_app:other@db.internal:5432/korpus"
    with pytest.raises(ValueError, match="distinct from protected PostgreSQL logins"):
        RlsIdentityBinder(PRIMARY, same_login, {}, review_database_url=REVIEW)


def test_identity_broker_login_cannot_equal_review_login() -> None:
    same_review = "postgresql+psycopg://korpus_review:other@db.internal:5432/korpus"
    with pytest.raises(ValueError, match="distinct from protected PostgreSQL logins"):
        RlsIdentityBinder(PRIMARY, same_review, {}, review_database_url=REVIEW)


def test_identity_broker_must_target_same_database() -> None:
    other_database = "postgresql+psycopg://korpus_identity:id@db.internal:5432/other"
    with pytest.raises(ValueError, match="must target the primary PostgreSQL database"):
        RlsIdentityBinder(PRIMARY, other_database, {}, review_database_url=REVIEW)


def test_sqlite_rejects_identity_broker_credential() -> None:
    with pytest.raises(ValueError, match="valid only with PostgreSQL"):
        RlsIdentityBinder(
            "sqlite:///./var/korpus.db",
            "postgresql+psycopg://korpus_identity:id@db.internal:5432/korpus",
            {},
        )


def test_base_repository_has_no_postgres_identity_fallback() -> None:
    connection = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    with pytest.raises(
        RuntimeError,
        match="PostgreSQL identity binding requires RlsBoundSqlRepository",
    ):
        SqlRepository._apply_postgres_identity(connection, object())
