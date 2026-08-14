#!/usr/bin/env python3
"""Provision separate PostgreSQL application and review-transition identities."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

APP_RW_TABLES = (
    "documents", "document_compartments", "evidence_spans", "span_embeddings", "ingestion_jobs",
    "accounts", "plans", "subscriptions", "billing_events", "conversations", "messages",
)
REVIEW_SELECT = ("documents", "document_versions", "evidence_spans", "audit_heads")
REVIEW_UPDATE = ("documents", "document_versions", "audit_heads")


def read_secret(name: str, file_name: str) -> str:
    direct, path = os.getenv(name), os.getenv(file_name)
    value = Path(path).read_text(encoding="utf-8").strip() if path else (direct or "")
    if not value:
        raise SystemExit(f"{name} or {file_name} is required")
    return value


def quoted(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def role_exists(connection, role: str) -> bool:
    query = text("SELECT 1 FROM pg_roles WHERE rolname=:role")
    return connection.execute(query, {"role": role}).scalar_one_or_none() is not None


def execute(connection, statement: str) -> None:
    connection.execute(text(statement))


def grant(connection, privileges: str, table: str, role: str) -> None:
    execute(connection, f"GRANT {privileges} ON TABLE {quoted(table)} TO {quoted(role)}")


def grant_many(connection, privileges: str, tables: tuple[str, ...], role: str) -> None:
    for table in tables:
        grant(connection, privileges, table, role)


def ensure_login(connection, role: str, password: str) -> None:
    verb, login = ("ALTER ROLE", "") if role_exists(connection, role) else ("CREATE ROLE", "LOGIN ")
    escaped = password.replace("'", "''")
    execute(
        connection,
        f"{verb} {quoted(role)} {login}NOSUPERUSER NOCREATEDB NOCREATEROLE "
        f"NOINHERIT NOBYPASSRLS CONNECTION LIMIT 64 PASSWORD '{escaped}'",
    )


def ensure_group(connection, role: str) -> None:
    if not role_exists(connection, role):
        execute(
            connection,
            f"CREATE ROLE {quoted(role)} NOLOGIN NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOBYPASSRLS",
        )


admin_url = os.environ["KORPUS_DATABASE_URL"]
app_role = os.getenv("KORPUS_POSTGRES_APP_ROLE", "korpus_app")
review_role = os.getenv("KORPUS_POSTGRES_REVIEW_ROLE", "korpus_review")
app_password = read_secret("KORPUS_POSTGRES_APP_PASSWORD", "KORPUS_POSTGRES_APP_PASSWORD_FILE")
review_password = read_secret(
    "KORPUS_POSTGRES_REVIEW_PASSWORD", "KORPUS_POSTGRES_REVIEW_PASSWORD_FILE"
)
database = make_url(admin_url).database or ""
if not database:
    raise SystemExit("PostgreSQL database name is required")

engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
with engine.connect() as connection:
    ensure_login(connection, app_role, app_password)
    ensure_login(connection, review_role, review_password)
    ensure_group(connection, "korpus_app_runtime")
    ensure_group(connection, "korpus_review_runtime")
    app_sql, review_sql, db_sql = quoted(app_role), quoted(review_role), quoted(database)
    execute(connection, f"GRANT korpus_app_runtime TO {app_sql}")
    execute(connection, f"GRANT korpus_review_runtime TO {review_sql}")
    execute(connection, f"REVOKE korpus_review_runtime FROM {app_sql}")
    execute(connection, f"REVOKE korpus_app_runtime FROM {review_sql}")
    execute(connection, "REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    for role_sql in (app_sql, review_sql):
        execute(connection, f"GRANT CONNECT ON DATABASE {db_sql} TO {role_sql}")
        execute(connection, f"GRANT USAGE ON SCHEMA public TO {role_sql}")
        execute(connection, f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role_sql}")
        execute(connection, f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role_sql}")
    grant_many(connection, "SELECT, INSERT, UPDATE, DELETE", APP_RW_TABLES, app_role)
    grant(connection, "SELECT, INSERT", "document_versions", app_role)
    execute(connection, f"GRANT UPDATE (rescinded_at, state_version) ON document_versions TO {app_sql}")
    grant(connection, "SELECT", "corpus_state_epoch", app_role)
    grant(connection, "SELECT, INSERT", "audit_events", app_role)
    grant_many(connection, "SELECT, INSERT, UPDATE", ("audit_anchor_outbox", "audit_heads"), app_role)
    grant_many(connection, "SELECT", REVIEW_SELECT, review_role)
    grant_many(connection, "UPDATE", REVIEW_UPDATE, review_role)
    grant_many(connection, "INSERT", ("audit_events", "audit_anchor_outbox"), review_role)
    grant(connection, "SELECT", "alembic_version", app_role)
    for role_sql in (app_sql, review_sql):
        execute(connection, f"ALTER ROLE {role_sql} SET statement_timeout='60s'")
        execute(connection, f"ALTER ROLE {role_sql} SET lock_timeout='5s'")
        execute(connection, f"ALTER ROLE {role_sql} SET idle_in_transaction_session_timeout='60s'")
engine.dispose()
print(f"prepared split roles: app={app_role}, review={review_role}, database={database}")
