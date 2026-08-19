#!/usr/bin/env python3
"""Create the non-superuser application role with an explicit fail-closed grant set."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, text

# Every table the application touches has to appear in exactly one of these lists —
# the role starts from REVOKE ALL, so an omission is a runtime InsufficientPrivilege
# rather than a lax grant. Two tables added by later migrations were missing:
# document_compartments (0004) and ingestion_jobs (0005). Nothing caught it because
# the SQLite configuration has no roles at all, and the PostgreSQL job had never run
# past migration 0001. test_postgres_role_grants.py now fails when a table exists in
# the metadata and in none of these lists.
READ_WRITE_TABLES = (
    "documents",
    "document_versions",
    "document_compartments",
    "evidence_spans",
    "span_embeddings",
    "ingestion_jobs",
    # ACT-001. Read-write rather than append-only: an account is disabled and re-enabled,
    # a subscription moves between states, a conversation is archived. What must not be
    # rewritable is the audit trail of those changes, and that is `audit_events` below.
    "accounts",
    "plans",
    "subscriptions",
    "billing_events",
    "conversations",
    "messages",
    # ACT-LRN-002. Learning content is written only while draft; PostgreSQL triggers
    # make published content immutable and invalidate it when canonical source state changes.
    "learning_courses",
    "learning_course_versions",
    "learning_modules",
    "learning_lessons",
    "learning_objectives",
    "learning_source_bindings",
    "learning_source_binding_spans",
    "learning_lesson_blocks",
    "learning_block_sources",
    "learning_prerequisites",
    "learning_publications",
)
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
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                f"{quoted_identifier(table_name)} TO {role_sql}"
            )
        )
    for table_name in AUDIT_APPEND_TABLES:
        connection.execute(
            text(f"GRANT SELECT, INSERT ON TABLE {quoted_identifier(table_name)} TO {role_sql}")
        )
    for table_name in AUDIT_MUTABLE_TABLES:
        connection.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE ON TABLE "
                f"{quoted_identifier(table_name)} TO {role_sql}"
            )
        )
    connection.execute(text(f"GRANT SELECT ON TABLE alembic_version TO {role_sql}"))
    # No blanket/default privileges: a new migration remains inaccessible until reviewed here.
    connection.execute(text(f"ALTER ROLE {role_sql} SET statement_timeout = '60s'"))
    connection.execute(text(f"ALTER ROLE {role_sql} SET lock_timeout = '5s'"))
    connection.execute(
        text(f"ALTER ROLE {role_sql} SET idle_in_transaction_session_timeout = '60s'")
    )
engine.dispose()
print(f"prepared least-privilege non-superuser PostgreSQL role: {app_role} on {database}")
