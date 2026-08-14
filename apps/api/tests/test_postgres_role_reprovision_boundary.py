from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError

from apps.api.tests.conftest import POSTGRES_ADMIN_URL
from scripts.postgres_role_hardening import quoted

ROOT = Path(__file__).resolve().parents[3]
APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL") or os.getenv("KORPUS_TEST_DATABASE_URL")
REVIEW_URL = os.getenv("KORPUS_REVIEW_DATABASE_URL")
IDENTITY_URL = os.getenv("RLS_IDENTITY_DATABASE_URL")
pytestmark = pytest.mark.postgres


def _credentials(url: str | None) -> tuple[str, str] | None:
    if not url:
        return None
    parsed: URL = make_url(url)
    if not parsed.username or parsed.password is None:
        return None
    return parsed.username, str(parsed.password)


def _reprovision() -> None:
    app = _credentials(APP_URL)
    review = _credentials(REVIEW_URL)
    identity = _credentials(IDENTITY_URL)
    if not POSTGRES_ADMIN_URL or not app or not review or not identity:
        pytest.skip("split PostgreSQL admin/app/review/identity credentials are required")
    env = {
        **os.environ,
        "KORPUS_DATABASE_URL": POSTGRES_ADMIN_URL,
        "KORPUS_POSTGRES_APP_ROLE": app[0],
        "KORPUS_POSTGRES_APP_PASSWORD": app[1],
        "KORPUS_POSTGRES_REVIEW_ROLE": review[0],
        "KORPUS_POSTGRES_REVIEW_PASSWORD": review[1],
        "KORPUS_POSTGRES_IDENTITY_ROLE": identity[0],
        "KORPUS_POSTGRES_IDENTITY_PASSWORD": identity[1],
    }
    completed = subprocess.run(
        [sys.executable, "scripts/prepare_postgres_role.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("target_url", [APP_URL, REVIEW_URL, IDENTITY_URL])
def test_real_reprovision_destroys_stale_bypass_membership(target_url: str | None) -> None:
    credentials = _credentials(target_url)
    if not POSTGRES_ADMIN_URL or not target_url or not credentials:
        pytest.skip("split PostgreSQL role URL is required")
    target_role, _password = credentials
    stale_role = f"korpus_stale_bypass_{target_role}_{os.getpid()}"
    stale_sql, target_sql = quoted(stale_role), quoted(target_role)
    admin = create_engine(POSTGRES_ADMIN_URL, future=True, pool_pre_ping=True)
    target = create_engine(target_url, future=True, pool_pre_ping=True)
    try:
        with admin.begin() as connection:
            connection.execute(text(f"DROP ROLE IF EXISTS {stale_sql}"))
            connection.execute(text(f"CREATE ROLE {stale_sql} NOLOGIN BYPASSRLS"))
            connection.execute(text(f"GRANT {stale_sql} TO {target_sql}"))
        with target.begin() as connection:
            connection.execute(text(f"SET LOCAL ROLE {stale_sql}"))
            assert connection.execute(text("SELECT current_user")).scalar_one() == stale_role
        target.dispose()

        _reprovision()

        with admin.connect() as connection:
            still_member = connection.execute(
                text("SELECT pg_catalog.pg_has_role(:member,:parent,'MEMBER')"),
                {"member": target_role, "parent": stale_role},
            ).scalar_one()
        assert still_member is False

        target = create_engine(target_url, future=True, pool_pre_ping=True)
        with pytest.raises(DBAPIError), target.begin() as connection:
            connection.execute(text(f"SET LOCAL ROLE {stale_sql}"))
    finally:
        target.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"REVOKE {stale_sql} FROM {target_sql}"))
            connection.execute(text(f"DROP ROLE IF EXISTS {stale_sql}"))
        admin.dispose()
