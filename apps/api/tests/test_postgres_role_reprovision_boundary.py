from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from apps.api.tests.conftest import POSTGRES_ADMIN_URL
from scripts.postgres_role_hardening import quoted, revoke_all_memberships

APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL") or os.getenv("KORPUS_TEST_DATABASE_URL")
pytestmark = pytest.mark.postgres


def test_reprovision_destroys_stale_bypass_membership() -> None:
    if not APP_URL or not POSTGRES_ADMIN_URL:
        pytest.skip("split PostgreSQL app/admin URLs are required")
    app_role = make_url(APP_URL).username
    if not app_role:
        pytest.skip("PostgreSQL application login is required")
    stale_role = f"korpus_stale_bypass_{os.getpid()}"
    stale_sql, app_sql = quoted(stale_role), quoted(app_role)
    admin = create_engine(POSTGRES_ADMIN_URL, future=True, pool_pre_ping=True)
    app = create_engine(APP_URL, future=True, pool_pre_ping=True)
    try:
        with admin.begin() as connection:
            connection.execute(text(f"DROP ROLE IF EXISTS {stale_sql}"))
            connection.execute(text(f"CREATE ROLE {stale_sql} NOLOGIN BYPASSRLS"))
            connection.execute(text(f"GRANT {stale_sql} TO {app_sql}"))
        with app.begin() as connection:
            connection.execute(text(f"SET LOCAL ROLE {stale_sql}"))
            assert connection.execute(text("SELECT current_user")).scalar_one() == stale_role
        app.dispose()

        with admin.begin() as connection:
            revoke_all_memberships(connection, app_role)
            connection.execute(text(f"GRANT korpus_app_runtime TO {app_sql}"))
            still_member = connection.execute(
                text("SELECT pg_catalog.pg_has_role(:member,:parent,'MEMBER')"),
                {"member": app_role, "parent": stale_role},
            ).scalar_one()
            assert still_member is False

        app = create_engine(APP_URL, future=True, pool_pre_ping=True)
        with pytest.raises(DBAPIError), app.begin() as connection:
            connection.execute(text(f"SET LOCAL ROLE {stale_sql}"))
    finally:
        app.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"REVOKE {stale_sql} FROM {app_sql}"))
            connection.execute(text(f"DROP ROLE IF EXISTS {stale_sql}"))
        admin.dispose()
