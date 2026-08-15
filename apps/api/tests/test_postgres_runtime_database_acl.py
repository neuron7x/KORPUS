from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL") or os.getenv("KORPUS_TEST_DATABASE_URL")
REVIEW_URL = os.getenv("KORPUS_REVIEW_DATABASE_URL")
IDENTITY_URL = os.getenv("RLS_IDENTITY_DATABASE_URL")
pytestmark = pytest.mark.postgres

RUNTIME = (
    APP_URL,
    REVIEW_URL,
    IDENTITY_URL,
)
GROUPS = (
    "korpus_app_runtime",
    "korpus_review_runtime",
    "korpus_identity_runtime",
)


def _require(url: str | None) -> str:
    if not url:
        pytest.skip("split PostgreSQL app/review/identity URLs are required")
    return url


@pytest.mark.parametrize("url", RUNTIME)
def test_runtime_login_has_connect_and_usage_but_no_create_or_temp(url: str | None) -> None:
    engine = create_engine(_require(url), future=True, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            privileges = connection.execute(
                text(
                    "SELECT "
                    "pg_catalog.has_database_privilege(current_user,current_database(),'CONNECT'), "
                    "pg_catalog.has_database_privilege(current_user,current_database(),'CREATE'), "
                    "pg_catalog.has_database_privilege(current_user,current_database(),'TEMPORARY'), "
                    "pg_catalog.has_schema_privilege(current_user,'public','USAGE'), "
                    "pg_catalog.has_schema_privilege(current_user,'public','CREATE')"
                )
            ).one()
        assert tuple(bool(value) for value in privileges) == (True, False, False, True, False)
    finally:
        engine.dispose()


def test_runtime_marker_groups_have_zero_database_and_schema_privilege() -> None:
    engine = create_engine(_require(APP_URL), future=True, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            for group in GROUPS:
                privileges = connection.execute(
                    text(
                        "SELECT "
                        "pg_catalog.has_database_privilege(:role,current_database(),'CONNECT'), "
                        "pg_catalog.has_database_privilege(:role,current_database(),'CREATE'), "
                        "pg_catalog.has_database_privilege(:role,current_database(),'TEMPORARY'), "
                        "pg_catalog.has_schema_privilege(:role,'public','USAGE'), "
                        "pg_catalog.has_schema_privilege(:role,'public','CREATE')"
                    ),
                    {"role": group},
                ).one()
                assert tuple(bool(value) for value in privileges) == (
                    False,
                    False,
                    False,
                    False,
                    False,
                )
    finally:
        engine.dispose()
