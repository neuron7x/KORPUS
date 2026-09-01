"""Примітиви керування ролями PostgreSQL — по одному твердженню на функцію.

Портовано з GitHub-лінії 01.09.2026. `prepare_postgres_role.py` тримав це
вбудованим, і кожне нове правило дописувалось до однієї довгої процедури, де
порядок `REVOKE`/`GRANT` не було видно. Найважливіший тут `revoke_all_memberships`:
переприв'язка ролі мусить ЗНИЩУВАТИ застаріле членство, інакше роль зберігає
права, яких їй уже не давали, і жоден `GRANT` цього не покаже.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


def quoted(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def execute(connection: Connection, statement: str) -> None:
    connection.execute(text(statement))


def _role_exists(connection: Connection, role: str) -> bool:
    return (
        connection.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}
        ).scalar_one_or_none()
        is not None
    )


def ensure_login(connection: Connection, role: str, password: str) -> None:
    verb, login = (
        ("ALTER ROLE", "") if _role_exists(connection, role) else ("CREATE ROLE", "LOGIN ")
    )
    escaped = password.replace("'", "''")
    execute(
        connection,
        f"{verb} {quoted(role)} {login}NOSUPERUSER NOCREATEDB NOCREATEROLE "
        f"NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 64 PASSWORD '{escaped}'",
    )


def ensure_group(connection: Connection, role: str) -> None:
    role_sql = quoted(role)
    if not _role_exists(connection, role):
        execute(connection, f"CREATE ROLE {role_sql} NOLOGIN")
    execute(
        connection,
        f"ALTER ROLE {role_sql} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
        "NOINHERIT NOREPLICATION NOBYPASSRLS",
    )


def revoke_all_memberships(connection: Connection, role: str) -> None:
    memberships = (
        connection.execute(
            text(
                "SELECT parent.rolname FROM pg_catalog.pg_auth_members membership "
                "JOIN pg_catalog.pg_roles parent ON parent.oid=membership.roleid "
                "JOIN pg_catalog.pg_roles member ON member.oid=membership.member "
                "WHERE member.rolname=:role"
            ),
            {"role": role},
        )
        .scalars()
        .all()
    )
    for parent in memberships:
        execute(connection, f"REVOKE {quoted(str(parent))} FROM {quoted(role)}")
