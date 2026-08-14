from __future__ import annotations

from sqlalchemy import text


def quoted(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def execute(connection, statement: str) -> None:
    connection.execute(text(statement))


def _role_exists(connection, role: str) -> bool:
    return connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}
    ).scalar_one_or_none() is not None


def ensure_login(connection, role: str, password: str) -> None:
    verb, login = ("ALTER ROLE", "") if _role_exists(connection, role) else ("CREATE ROLE", "LOGIN ")
    escaped = password.replace("'", "''")
    execute(
        connection,
        f"{verb} {quoted(role)} {login}NOSUPERUSER NOCREATEDB NOCREATEROLE "
        f"NOINHERIT NOBYPASSRLS CONNECTION LIMIT 64 PASSWORD '{escaped}'",
    )


def ensure_group(connection, role: str) -> None:
    role_sql = quoted(role)
    if not _role_exists(connection, role):
        execute(connection, f"CREATE ROLE {role_sql} NOLOGIN")
    execute(
        connection,
        f"ALTER ROLE {role_sql} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
        "NOINHERIT NOBYPASSRLS",
    )


def revoke_all_memberships(connection, role: str) -> None:
    memberships = connection.execute(
        text(
            "SELECT parent.rolname FROM pg_catalog.pg_auth_members membership "
            "JOIN pg_catalog.pg_roles parent ON parent.oid=membership.roleid "
            "JOIN pg_catalog.pg_roles member ON member.oid=membership.member "
            "WHERE member.rolname=:role"
        ),
        {"role": role},
    ).scalars().all()
    for parent in memberships:
        execute(connection, f"REVOKE {quoted(str(parent))} FROM {quoted(role)}")
