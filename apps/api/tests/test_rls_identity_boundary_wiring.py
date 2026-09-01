"""Межа існує лише тоді, коли її НЕМОЖЛИВО не ввімкнути.

Деструктивний контроль самої межі вимагає живого PostgreSQL і живе в
`test_postgres_rls_claim_forgery.py`. Тут — два твердження, які не потребують СУБД
і які, якби їх не було, дали б хибне відчуття безпеки: що на PostgreSQL береться
САМЕ той репозиторій, і що брокер не може виявитись тим самим логіном, від якого
він боронить.
"""

from __future__ import annotations

import pytest
from korpus.config import Settings
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.rls_repository import RlsBoundSqlRepository
from korpus.infrastructure.runtime import create_repository

PRIMARY = "postgresql+psycopg://korpus_app:secret@db.invalid:5432/korpus"


def test_postgres_always_gets_the_boundary_bound_repository(tmp_path, monkeypatch) -> None:
    """Вибір за прапорцем лишив би дірку вмикною одним рядком конфігурації."""
    captured: dict[str, object] = {}

    class _Probe(RlsBoundSqlRepository):
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["factory"] = "rls"
            captured["authz"] = kwargs.get("authz_database_url")

    monkeypatch.setattr("korpus.infrastructure.runtime.RlsBoundSqlRepository", _Probe)
    settings = Settings(
        environment="test",
        database_url=PRIMARY,
        authz_database_url="postgresql+psycopg://korpus_authz:other@db.invalid:5432/korpus",
        audit_hmac_key="k" * 32,
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
    )
    create_repository(settings)

    assert captured["factory"] == "rls"
    assert captured["authz"] == ("postgresql+psycopg://korpus_authz:other@db.invalid:5432/korpus")


def test_sqlite_keeps_the_plain_repository(tmp_path, monkeypatch) -> None:
    """Негативний контроль: на SQLite брокера немає й бути не може."""
    captured: dict[str, object] = {}

    class _Probe(SqlRepository):
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["factory"] = "plain"
            captured["authz"] = "authz_database_url" in kwargs

    monkeypatch.setattr("korpus.infrastructure.runtime.SqlRepository", _Probe)
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        audit_hmac_key="k" * 32,
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
    )
    create_repository(settings)

    assert captured["factory"] == "plain"
    assert captured["authz"] is False


@pytest.mark.parametrize(
    ("authz", "message"),
    [
        (None, "separate authz database identity"),
        (PRIMARY, "distinct PostgreSQL login"),
        (
            "postgresql+psycopg://korpus_authz:x@other.invalid:5432/korpus",
            "must target the primary PostgreSQL database",
        ),
        (
            "postgresql+psycopg://korpus_authz:x@db.invalid:5432/other",
            "must target the primary PostgreSQL database",
        ),
        (
            "sqlite:///./var/korpus.db",
            "must target the primary PostgreSQL database",
        ),
    ],
)
def test_a_broker_that_is_not_a_separate_login_is_refused(authz: str | None, message: str) -> None:
    """Брокер, що збігається із застосунковим логіном, — це та сама дірка під іншим ім'ям."""
    with pytest.raises(ValueError, match=message):
        RlsBoundSqlRepository._validate_authz_url(PRIMARY, authz)


def test_a_distinct_broker_on_the_same_database_is_accepted() -> None:
    """Дуал: перевірка, що відхиляє все, — не перевірка."""
    RlsBoundSqlRepository._validate_authz_url(
        PRIMARY, "postgresql+psycopg://korpus_authz:x@db.invalid:5432/korpus"
    )
