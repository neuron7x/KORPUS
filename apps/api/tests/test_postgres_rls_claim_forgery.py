"""RLS мусить тримати ПРОТИ звичайного застосункового логіна, а не разом із ним.

Виміряно запуском 01.09.2026 на канонічному дереві, ДО правки: логін `korpus_app`
виконав `set_config('korpus.clearance','3')` і `set_config('korpus.roles','admin')`
у власній транзакції й ПОБАЧИВ та ЗАПИСАВ документ грифу `restricted`, якого чесна
особистість не бачила. Політики читали `current_setting`, а ці ж значення писав сам
застосунок — RLS вірила тому, кого мала обмежувати.

Тепер claim'и живуть у `public.korpus_rls_context`, застосунковий логін не має до неї
жодного доступу й не має права викликати брокера. Три маршрути підробки перевіряються
окремо, бо закритий один із них нічого не каже про два інші.

Позитивний контроль тут ОБОВ'ЯЗКОВИЙ і стоїть поруч: межа, яка відмовляє всім,
виглядає як безпека і є поломкою. `test_the_authorized_flow_still_sees_what_it_may`
питає саме те, що відмови приховують.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.rls_repository import RlsBoundSqlRepository
from sqlalchemy import create_engine, text

from apps.api.tests.conftest import reset_database

APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL")
ADMIN_URL = os.getenv("KORPUS_TEST_DATABASE_ADMIN_URL")
AUTHZ_URL = os.getenv("KORPUS_AUTHZ_DATABASE_URL")
pytestmark = pytest.mark.postgres

_CONFIGURED = bool(APP_URL and ADMIN_URL and AUTHZ_URL)
_REASON = (
    "KORPUS_POSTGRES_TEST_URL / KORPUS_TEST_DATABASE_ADMIN_URL / "
    "KORPUS_AUTHZ_DATABASE_URL are not configured"
)


def _insert(admin_url: str, *, tier: int, corpus: str, classification: str) -> str:
    document_id = str(uuid4())
    engine = create_engine(admin_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO documents(id, canonical_title, corpus_id, issuer, "
                    "jurisdiction, document_type, access_tier, classification, "
                    "created_at, compartments_json) VALUES (:id, :title, :corpus, 'ГШ', "
                    "'UA', 'order', :tier, :classification, :now, '[]')"
                ),
                {
                    "id": document_id,
                    "title": f"Документ {document_id[:8]}",
                    "corpus": corpus,
                    "tier": tier,
                    "classification": classification,
                    "now": datetime.now(UTC),
                },
            )
    finally:
        engine.dispose()
    return document_id


def _visible(connection, document_id: str) -> bool:
    found = connection.execute(
        text("SELECT count(*) FROM documents WHERE id = :id"), {"id": document_id}
    ).scalar()
    return bool(found)


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
def test_session_settings_cannot_raise_the_readers_own_clearance() -> None:
    reset_database()
    assert ADMIN_URL and APP_URL
    secret = _insert(ADMIN_URL, tier=3, corpus="restricted-demo", classification="restricted")
    engine = create_engine(APP_URL, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT set_config('korpus.clearance','3',true), "
                    "set_config('korpus.corpora','public,restricted-demo',true), "
                    "set_config('korpus.classifications','public,internal,restricted',true), "
                    "set_config('korpus.compartments','',true), "
                    "set_config('korpus.roles','user,admin',true)"
                )
            )
            assert not _visible(connection, secret)
    finally:
        engine.dispose()


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
def test_the_application_login_cannot_touch_the_context_table() -> None:
    reset_database()
    assert APP_URL
    engine = create_engine(APP_URL, future=True)
    try:
        for statement in (
            "SELECT * FROM public.korpus_rls_context",
            "UPDATE public.korpus_rls_context SET clearance = 3",
            "INSERT INTO public.korpus_rls_context(backend_pid, transaction_id, "
            "session_login, subject, clearance, corpora, classifications, compartments, "
            "roles) VALUES (pg_backend_pid(), txid_current(), session_user, 'x', 3, "
            "ARRAY['public'], ARRAY['public'], ARRAY[]::text[], ARRAY['admin'])",
        ):
            with engine.begin() as connection, pytest.raises(Exception) as raised:
                connection.execute(text(statement))
            assert "permission denied" in str(raised.value)
    finally:
        engine.dispose()


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
def test_the_application_login_cannot_call_the_broker() -> None:
    reset_database()
    assert APP_URL
    engine = create_engine(APP_URL, future=True)
    try:
        with engine.begin() as connection, pytest.raises(Exception) as raised:
            connection.execute(
                text(
                    "SELECT public.korpus_bind_rls_context(pg_backend_pid(), "
                    "txid_current(), session_user, 'x', 3, '[\"public\"]'::jsonb, "
                    "'[\"public\"]'::jsonb, '[]'::jsonb, '[\"admin\"]'::jsonb)"
                )
            )
        assert "permission denied" in str(raised.value)
    finally:
        engine.dispose()


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
def test_the_authorized_flow_still_sees_what_it_may() -> None:
    """Позитивний контроль. Межа, яка відмовляє всім, — не межа, а поломка."""
    reset_database()
    assert ADMIN_URL and APP_URL and AUTHZ_URL
    public_document = _insert(ADMIN_URL, tier=0, corpus="public", classification="public")
    secret = _insert(ADMIN_URL, tier=3, corpus="restricted-demo", classification="restricted")
    repository = RlsBoundSqlRepository(APP_URL, "k" * 32, authz_database_url=AUTHZ_URL)
    try:
        reader = Identity(
            subject="reader",
            roles=frozenset({"user"}),
            clearance=AccessTier.PUBLIC,
            corpora=frozenset({"public"}),
        )
        officer = Identity(
            subject="officer",
            roles=frozenset({"user", "admin"}),
            clearance=AccessTier.RESTRICTED,
            corpora=frozenset({"public", "restricted-demo"}),
        )
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, reader)
            assert _visible(connection, public_document)
            assert not _visible(connection, secret)
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, officer)
            assert _visible(connection, public_document)
            assert _visible(connection, secret)
    finally:
        repository.close()
