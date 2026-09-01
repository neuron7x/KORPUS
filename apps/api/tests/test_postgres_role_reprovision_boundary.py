"""Переприв'язка ролей мусить ЗНИЩУВАТИ дрейф прав, а не лише додавати нові.

`prepare_postgres_role.py` починає з `REVOKE ALL` і далі видає право за правом —
форма правильна, бо пропуск падає закрито. Але «видати наново» і «знищити чуже»
— різні твердження, і друге не випливає з першого.

Виміряно 01.09.2026, і саме вимір показав розрив. Вручну видані `BYPASSRLS`,
`CREATEDB`, батьківське членство й `GRANT SELECT` на таблицю контексту:

    korpus_app     BYPASSRLS знято, чужий батько знято
    korpus_authz   BYPASSRLS знято, чужий батько ВИЖИВ
    korpus_review  BYPASSRLS знято, чужий батько ВИЖИВ

Тобто властивість трималась рівно там, де для неї був написаний код, і не
узагальнювалась. Застаріле членство — це право, якого ролі вже не давали, і
жоден `GRANT` його не покаже: воно видиме лише в `pg_auth_members`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[3]
APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL") or os.getenv("KORPUS_TEST_DATABASE_URL")
ADMIN_URL = os.getenv("KORPUS_TEST_DATABASE_ADMIN_URL")
AUTHZ_URL = os.getenv("KORPUS_AUTHZ_DATABASE_URL")
REVIEW_URL = os.getenv("KORPUS_REVIEW_DATABASE_URL")
pytestmark = pytest.mark.postgres

_CONFIGURED = bool(APP_URL and ADMIN_URL and AUTHZ_URL and REVIEW_URL)
_REASON = "split PostgreSQL app/review/authz/admin URLs are required"
_DRIFT_PARENT = "korpus_reprovision_drift_probe"


def _credentials(url: str) -> tuple[str, str]:
    """Логін і пароль беруться з URL, який набір уже має.

    Окремі змінні оточення для паролів були б четвертим оголошенням того самого
    факту — рівно тим, що сьогодні вже коштувало пів дня хибних вироків.
    """
    parts = urlsplit(url)
    assert parts.username and parts.password
    return parts.username, parts.password


def _reprovision() -> None:
    assert APP_URL and ADMIN_URL and AUTHZ_URL and REVIEW_URL
    app_role, app_password = _credentials(APP_URL)
    authz_role, authz_password = _credentials(AUTHZ_URL)
    review_role, review_password = _credentials(REVIEW_URL)
    environment = {
        **os.environ,
        "KORPUS_DATABASE_URL": ADMIN_URL,
        "KORPUS_POSTGRES_ADMIN_URL": ADMIN_URL,
        "KORPUS_POSTGRES_APP_ROLE": app_role,
        "KORPUS_POSTGRES_APP_PASSWORD": app_password,
        "KORPUS_POSTGRES_AUTHZ_ROLE": authz_role,
        "KORPUS_POSTGRES_AUTHZ_PASSWORD": authz_password,
        "KORPUS_POSTGRES_REVIEW_ROLE": review_role,
        "KORPUS_POSTGRES_REVIEW_PASSWORD": review_password,
        "PYTHONPATH": str(ROOT / "apps/api/src"),
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/prepare_postgres_role.py")],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _observe(admin_url: str, roles: tuple[str, ...]) -> dict[str, tuple[bool, bool, list[str]]]:
    engine = create_engine(admin_url, future=True)
    try:
        with engine.connect() as connection:
            observed = {}
            for role in roles:
                flags = connection.execute(
                    text(
                        "SELECT rolbypassrls, rolcreatedb, rolsuper, rolcreaterole "
                        "FROM pg_catalog.pg_roles WHERE rolname = :role"
                    ),
                    {"role": role},
                ).one()
                parents = (
                    connection.execute(
                        text(
                            "SELECT parent.rolname FROM pg_catalog.pg_auth_members m "
                            "JOIN pg_catalog.pg_roles parent ON parent.oid = m.roleid "
                            "JOIN pg_catalog.pg_roles member ON member.oid = m.member "
                            "WHERE member.rolname = :role ORDER BY parent.rolname"
                        ),
                        {"role": role},
                    )
                    .scalars()
                    .all()
                )
                observed[role] = (
                    bool(flags.rolbypassrls) or bool(flags.rolsuper),
                    bool(flags.rolcreatedb) or bool(flags.rolcreaterole),
                    [str(name) for name in parents],
                )
            return observed
    finally:
        engine.dispose()


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
def test_reprovision_destroys_drift_on_every_runtime_login() -> None:
    assert APP_URL and ADMIN_URL and AUTHZ_URL and REVIEW_URL
    roles = tuple(_credentials(url)[0] for url in (APP_URL, AUTHZ_URL, REVIEW_URL))
    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", future=True)
    try:
        with engine.connect() as connection:
            connection.execute(text(f"DROP ROLE IF EXISTS {_DRIFT_PARENT}"))
            connection.execute(text(f"CREATE ROLE {_DRIFT_PARENT} NOLOGIN"))
            for role in roles:
                connection.execute(text(f'ALTER ROLE "{role}" BYPASSRLS CREATEDB'))
                connection.execute(text(f'GRANT {_DRIFT_PARENT} TO "{role}"'))
                connection.execute(
                    text(f'GRANT SELECT ON TABLE public.korpus_rls_context TO "{role}"')
                )

        drifted = _observe(ADMIN_URL, roles)
        assert all(state[0] and state[1] for state in drifted.values()), drifted
        assert all(_DRIFT_PARENT in state[2] for state in drifted.values()), drifted

        _reprovision()

        after = _observe(ADMIN_URL, roles)
        for role, (elevated, creator, parents) in after.items():
            assert elevated is False, (role, "BYPASSRLS/SUPERUSER пережив переприв'язку")
            assert creator is False, (role, "CREATEDB/CREATEROLE пережив переприв'язку")
            assert _DRIFT_PARENT not in parents, (role, parents)
        # Маркер застосунку — єдине членство, яке МУСИТЬ лишитись.
        assert after[roles[0]][2] == [f"{roles[0]}_runtime"], after[roles[0]]
        assert after[roles[1]][2] == []
        assert after[roles[2]][2] == []
    finally:
        with engine.connect() as connection:
            connection.execute(text(f"DROP ROLE IF EXISTS {_DRIFT_PARENT}"))
        engine.dispose()


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
def test_no_runtime_login_keeps_a_grant_on_the_binding_table() -> None:
    """Таблиця контексту — не площина даних: право на неї означало б підробку claim'ів."""
    assert ADMIN_URL and APP_URL and AUTHZ_URL and REVIEW_URL
    roles = [_credentials(url)[0] for url in (APP_URL, AUTHZ_URL, REVIEW_URL)]
    engine = create_engine(ADMIN_URL, future=True)
    try:
        with engine.connect() as connection:
            granted = connection.execute(
                text(
                    "SELECT grantee, privilege_type FROM information_schema.table_privileges "
                    "WHERE table_name = 'korpus_rls_context' AND grantee = ANY(:roles)"
                ),
                {"roles": roles},
            ).all()
        assert granted == [], granted
    finally:
        engine.dispose()


@pytest.mark.skipif(not _CONFIGURED, reason=_REASON)
def test_runtime_logins_may_connect_and_use_but_never_create() -> None:
    """CONNECT і USAGE — так; CREATE у схемі й TEMP у базі — ні."""
    assert ADMIN_URL
    for url in (APP_URL, AUTHZ_URL, REVIEW_URL):
        assert url
        engine = create_engine(url, future=True)
        try:
            with engine.connect() as connection:
                row = connection.execute(
                    text(
                        # Псевдоніми навмисно довгі: `t` збігається з застарілим
                        # `Row.t` у SQLAlchemy, і звертання мовчки віддавало б інше.
                        "SELECT "
                        "has_database_privilege(current_user, current_database(), 'CONNECT') "
                        "AS may_connect, "
                        "has_database_privilege(current_user, current_database(), 'TEMP') "
                        "AS may_temp, "
                        "has_database_privilege(current_user, current_database(), 'CREATE') "
                        "AS may_create_db, "
                        "has_schema_privilege(current_user, 'public', 'USAGE') AS may_use, "
                        "has_schema_privilege(current_user, 'public', 'CREATE') AS may_create"
                    )
                ).one()
            assert row.may_connect is True and row.may_use is True, url
            assert row.may_temp is False, url
            assert row.may_create_db is False and row.may_create is False, url
        finally:
            engine.dispose()
