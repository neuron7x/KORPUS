#!/usr/bin/env python3
"""Provision separate PostgreSQL application and review-transition identities."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, text

APP_RW_TABLES = (
    "documents", "document_compartments", "evidence_spans", "span_embeddings",
    "ingestion_jobs", "accounts", "plans", "subscriptions", "billing_events",
    "conversations", "messages",
)
READ_ONLY_TABLES = ("corpus_state_epoch",)
AUDIT_APPEND_TABLES = ("audit_events",)
AUDIT_MUTABLE_TABLES = ("audit_anchor_outbox", "audit_heads")
APP_VERSION_UPDATE_COLUMNS = ("rescinded_at", "state_version")
REVIEW_SELECT_TABLES = ("documents", "document_versions", "evidence_spans", "audit_heads")
REVIEW_UPDATE_TABLES = ("documents", "document_versions", "audit_heads")
REVIEW_INSERT_TABLES = ("audit_events", "audit_anchor_outbox")


def read_secret(name: str, file_name: str) -> str:
    direct = os.getenv(name)
    path = os.getenv(file_name)
    value = Path(path).read_text(encoding="utf-8").strip() if path else (direct or "")
    if not value:
        raise SystemExit(f"{name} or {file_name} is required")
    return value


def quoted(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def valid_role(value: str) -> str:
    if not value.replace("_", "").isalnum() or not value[0].isalpha():
        raise SystemExit(f"invalid PostgreSQL role: {value}")
    return value


def ensure_login(connection, role: str, password: str) -> None:
    role_sql = quoted(role)
    exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:r"), {"r": role}).scalar_one_or_none()
    verb, login = ("ALTER ROLE", "") if exists is not None else ("CREATE ROLE", "LOGIN ")
    escaped = password.replace("'", "''")
    connection.execute(text(f"{verb} {role_sql} {login}NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS CONNECTION LIMIT 64 PASSWORD '{escaped}'"))


def ensure_group(connection, role: str) -> None:
    if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:r"), {"r": role}).scalar_one_or_none() is None:
        connection.execute(text(f"CREATE ROLE {quoted(role)} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"))


admin_url = os.environ["KORPUS_DATABASE_URL"]
app_role = valid_role(os.getenv("KORPUS_POSTGRES_APP_ROLE", "korpus_app"))
review_role = valid_role(os.getenv("KORPUS_POSTGRES_REVIEW_ROLE", "korpus_review"))
app_password = read_secret("KORPUS_POSTGRES_APP_PASSWORD", "KORPUS_POSTGRES_APP_PASSWORD_FILE")
review_password = read_secret("KORPUS_POSTGRES_REVIEW_PASSWORD", "KORPUS_POSTGRES_REVIEW_PASSWORD_FILE")
parsed = urlparse(admin_url.replace("postgresql+psycopg", "postgresql", 1))
database = parsed.path.lstrip("/")
if not database or not database.replace("_", "").replace("-", "").isalnum():
    raise SystemExit("invalid PostgreSQL database name")

engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
with engine.connect() as connection:
    ensure_login(connection, app_role, app_password)
    ensure_login(connection, review_role, review_password)
    ensure_group(connection, "korpus_app_runtime")
    ensure_group(connection, "korpus_review_runtime")
    app_sql, review_sql, db_sql = quoted(app_role), quoted(review_role), quoted(database)
    connection.execute(text(f"GRANT korpus_app_runtime TO {app_sql}"))
    connection.execute(text(f"GRANT korpus_review_runtime TO {review_sql}"))
    connection.execute(text(f"REVOKE korpus_review_runtime FROM {app_sql}"))
    connection.execute(text(f"REVOKE korpus_app_runtime FROM {review_sql}"))
    connection.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
    for role_sql in (app_sql, review_sql):
        connection.execute(text(f"GRANT CONNECT ON DATABASE {db_sql} TO {role_sql}"))
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role_sql}"))
        connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role_sql}"))
        connection.execute(text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role_sql}"))
    for table_name in APP_RW_TABLES:
        connection.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {quoted(table_name)} TO {app_sql}"))
    connection.execute(text(f"GRANT SELECT, INSERT ON TABLE document_versions TO {app_sql}"))
    columns = ", ".join(APP_VERSION_UPDATE_COLUMNS)
    connection.execute(text(f"GRANT UPDATE ({columns}) ON TABLE document_versions TO {app_sql}"))
    for table_name in READ_ONLY_TABLES:
        connection.execute(text(f"GRANT SELECT ON TABLE {quoted(table_name)} TO {app_sql}"))
    for table_name in AUDIT_APPEND_TABLES:
        connection.execute(text(f"GRANT SELECT, INSERT ON TABLE {quoted(table_name)} TO {app_sql}"))
    for table_name in AUDIT_MUTABLE_TABLES:
        connection.execute(text(f"GRANT SELECT, INSERT, UPDATE ON TABLE {quoted(table_name)} TO {app_sql}"))
    for table_name in REVIEW_SELECT_TABLES:
        connection.execute(text(f"GRANT SELECT ON TABLE {quoted(table_name)} TO {review_sql}"))
    for table_name in REVIEW_UPDATE_TABLES:
        connection.execute(text(f"GRANT UPDATE ON TABLE {quoted(table_name)} TO {review_sql}"))
    for table_name in REVIEW_INSERT_TABLES:
        connection.execute(text(f"GRANT INSERT ON TABLE {quoted(table_name)} TO {review_sql}"))
    connection.execute(text(f"GRANT SELECT ON TABLE alembic_version TO {app_sql}"))
    for role_sql in (app_sql, review_sql):
        connection.execute(text(f"ALTER ROLE {role_sql} SET statement_timeout='60s'"))
        connection.execute(text(f"ALTER ROLE {role_sql} SET lock_timeout='5s'"))
        connection.execute(text(f"ALTER ROLE {role_sql} SET idle_in_transaction_session_timeout='60s'"))
engine.dispose()
print(f"prepared split PostgreSQL roles: app={app_role}, review={review_role}, database={database}")
