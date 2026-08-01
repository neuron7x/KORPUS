#!/usr/bin/env python3
"""Create the non-superuser application role with an explicit fail-closed grant set."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, text


READ_WRITE_TABLES = ("documents", "document_versions", "evidence_spans", "span_embeddings")
AUDIT_APPEND_TABLES = ("audit_events",)
AUDIT_MUTABLE_TABLES = ("audit_anchor_outbox", "audit_heads")


def read_secret(name: str, file_name: str) -> str:
    direct = os.getenv(name)
    path = os.getenv(file_name)
    value = Path(path).read_text(encoding="utf-8").strip() if path else (direct or "")
    if not value:
        raise SystemExit(f"{name} or {file_name} is required")
    return value


def quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


admin_url = os.environ["KORPUS_DATABASE_URL"]
app_role = os.getenv("KORPUS_POSTGRES_APP_ROLE", "korpus_app")
app_password = read_secret("KORPUS_POSTGRES_APP_PASSWORD", "KORPUS_POSTGRES_APP_PASSWORD_FILE")
if not app_role.replace("_", "").isalnum() or not app_role[0].isalpha():
    raise SystemExit("invalid PostgreSQL application role")
parsed = urlparse(admin_url.replace("postgresql+psycopg", "postgresql", 1))
database = parsed.path.lstrip("/")
if not database or not database.replace("_", "").replace("-", "").isalnum():
    raise SystemExit("invalid PostgreSQL database name")

engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
role_sql = quoted_identifier(app_role)
database_sql = quoted_identifier(database)
escaped_password = app_password.replace("'", "''")
with engine.connect() as connection:
    exists = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": app_role}
    ).scalar_one_or_none()
    verb = "ALTER ROLE" if exists is not None else "CREATE ROLE"
    login = "" if exists is not None else "LOGIN "
    connection.execute(
        text(
            f"{verb} {role_sql} {login}NOSUPERUSER NOCREATEDB NOCREATEROLE "
            f"NOINHERIT NOBYPASSRLS CONNECTION LIMIT 64 PASSWORD '{escaped_password}'"
        )
    )
    connection.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
    connection.execute(text(f"GRANT CONNECT ON DATABASE {database_sql} TO {role_sql}"))
    connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role_sql}"))
    connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role_sql}"))
    connection.execute(text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role_sql}"))
    for table_name in READ_WRITE_TABLES:
        connection.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {quoted_identifier(table_name)} TO {role_sql}")
        )
    for table_name in AUDIT_APPEND_TABLES:
        connection.execute(
            text(f"GRANT SELECT, INSERT ON TABLE {quoted_identifier(table_name)} TO {role_sql}")
        )
    for table_name in AUDIT_MUTABLE_TABLES:
        connection.execute(
            text(f"GRANT SELECT, INSERT, UPDATE ON TABLE {quoted_identifier(table_name)} TO {role_sql}")
        )
    connection.execute(text(f"GRANT SELECT ON TABLE alembic_version TO {role_sql}"))
    # No blanket/default privileges: a new migration remains inaccessible until reviewed here.
    connection.execute(text(f"ALTER ROLE {role_sql} SET statement_timeout = '60s'"))
    connection.execute(text(f"ALTER ROLE {role_sql} SET lock_timeout = '5s'"))
    connection.execute(text(f"ALTER ROLE {role_sql} SET idle_in_transaction_session_timeout = '60s'"))
engine.dispose()
print(f"prepared least-privilege non-superuser PostgreSQL role: {app_role} on {database}")
