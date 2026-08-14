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
    subject="rls-lifecycle-low",
    roles=frozenset({"user"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public-corpus"}),
)


def _engine(url: str):
    return create_engine(url, future=True, pool_pre_ping=True)


def test_binding_age_cannot_reopen_same_transaction_for_stronger_claims() -> None:
    if not APP_URL or not REVIEW_URL or not IDENTITY_URL or not POSTGRES_ADMIN_URL:
        pytest.skip("split PostgreSQL app/review/identity URLs are required")
    reset_database()
    app = _engine(APP_URL)
    broker = _engine(IDENTITY_URL)
    admin = _engine(POSTGRES_ADMIN_URL)
    binder = RlsIdentityBinder(
        APP_URL,
        IDENTITY_URL,
        {"future": True, "pool_pre_ping": True},
        review_database_url=REVIEW_URL,
    )
    try:
        with app.begin() as target:
            binder.bind(target, LOW)
            pid, backend_start, txid, login_name = target.execute(
                text(
                    "SELECT pg_catalog.pg_backend_pid(), a.backend_start, "
                    "pg_catalog.pg_current_xact_id()::text, session_user "
                    "FROM pg_catalog.pg_stat_activity a "
                    "WHERE a.pid=pg_catalog.pg_backend_pid()"
                )
            ).one()
            with admin.begin() as owner:
                changed = owner.execute(
                    text(
                        "UPDATE public.korpus_rls_identity_bindings "
                        "SET bound_at=statement_timestamp()-interval '2 days' "
                        "WHERE backend_pid=:pid AND backend_start=:start "
                        "AND transaction_id=:txid AND login_name=:login"
                    ),
                    {
                        "pid": pid,
                        "start": backend_start,
                        "txid": txid,
                        "login": login_name,
                    },
                )
                assert changed.rowcount == 1

            with pytest.raises(DBAPIError), broker.begin() as control:
                control.execute(
                    text(
                        "SELECT public.korpus_bind_rls_identity("
                        ":pid,:start,:txid,:login,'forged',3,'secret-corpus',"
                        "'public,internal,restricted','omega','admin,curator')"
                    ),
                    {
                        "pid": pid,
                        "start": backend_start,
                        "txid": txid,
                        "login": login_name,
                    },
                )

            clearance, corpora, roles = target.execute(
                text(
                    "SELECT public.korpus_rls_clearance(), "
                    "public.korpus_rls_corpora(), public.korpus_rls_roles()"
                )
            ).one()
            assert clearance == 0
            assert list(corpora) == ["public-corpus"]
            assert list(roles) == ["user"]
    finally:
        binder.close()
        app.dispose()
        broker.dispose()
        admin.dispose()
