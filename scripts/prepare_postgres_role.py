#!/usr/bin/env python3
"""Provision isolated PostgreSQL application, review, and RLS-identity logins."""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from postgres_role_hardening import (
    ensure_group, ensure_login, execute, quoted, revoke_all_memberships,
)

APP_RW_TABLES = (
    "documents", "document_compartments", "evidence_spans", "span_embeddings", "ingestion_jobs",
    "accounts", "plans", "subscriptions", "billing_events", "conversations", "messages",
)
REVIEW_SELECT = ("documents", "document_versions", "evidence_spans", "audit_heads")
REVIEW_UPDATE = ("documents", "document_versions", "audit_heads")
RLS_ACCESSORS = (
    "korpus_rls_clearance()", "korpus_rls_corpora()", "korpus_rls_classifications()",
    "korpus_rls_compartments()", "korpus_rls_roles()",
)
RLS_BINDER = "korpus_bind_rls_identity(integer,timestamptz,text,text,text,integer,text,text,text,text)"


def read_secret(name: str, file_name: str) -> str:
    direct, path = os.getenv(name), os.getenv(file_name)
    value = Path(path).read_text(encoding="utf-8").strip() if path else (direct or "")
    if not value:
        raise SystemExit(f"{name} or {file_name} is required")
    return value


def grant(connection, privileges: str, table: str, role: str) -> None:
    execute(connection, f"GRANT {privileges} ON TABLE {quoted(table)} TO {quoted(role)}")


def grant_many(connection, privileges: str, tables: tuple[str, ...], role: str) -> None:
    for table in tables:
        grant(connection, privileges, table, role)


def grant_execute(connection, function: str, role: str) -> None:
    execute(connection, f"GRANT EXECUTE ON FUNCTION {function} TO {quoted(role)}")


admin_url = os.environ["KORPUS_DATABASE_URL"]
app_role = os.getenv("KORPUS_POSTGRES_APP_ROLE", "korpus_app")
review_role = os.getenv("KORPUS_POSTGRES_REVIEW_ROLE", "korpus_review")
identity_role = os.getenv("KORPUS_POSTGRES_IDENTITY_ROLE", "korpus_identity")
app_password = read_secret("KORPUS_POSTGRES_APP_PASSWORD", "KORPUS_POSTGRES_APP_PASSWORD_FILE")
review_password = read_secret("KORPUS_POSTGRES_REVIEW_PASSWORD", "KORPUS_POSTGRES_REVIEW_PASSWORD_FILE")
identity_password = read_secret("KORPUS_POSTGRES_IDENTITY_PASSWORD", "KORPUS_POSTGRES_IDENTITY_PASSWORD_FILE")
database = make_url(admin_url).database or ""
if not database:
    raise SystemExit("PostgreSQL database name is required")
if len({app_role, review_role, identity_role}) != 3:
    raise SystemExit("application, review, and RLS identity logins must be distinct")

groups = ("korpus_app_runtime", "korpus_review_runtime", "korpus_identity_runtime")
engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
with engine.connect() as connection:
    for role, password in (
        (app_role, app_password), (review_role, review_password), (identity_role, identity_password)
    ):
        ensure_login(connection, role, password)
    for group in groups:
        ensure_group(connection, group)
    for role in (app_role, review_role, identity_role, *groups):
        revoke_all_memberships(connection, role)
    app_sql, review_sql, identity_sql = quoted(app_role), quoted(review_role), quoted(identity_role)
    principal_sqls = tuple(quoted(role) for role in (app_role, review_role, identity_role, *groups))
    db_sql = quoted(database)
    membership = "WITH ADMIN FALSE, INHERIT FALSE, SET FALSE"
    for group, role_sql in zip(groups, (app_sql, review_sql, identity_sql), strict=True):
        execute(connection, f"GRANT {group} TO {role_sql} {membership}")
    execute(connection, "REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    for role_sql in principal_sqls:
        execute(connection, f"REVOKE ALL ON DATABASE {db_sql} FROM {role_sql}")
        execute(connection, f"REVOKE ALL ON SCHEMA public FROM {role_sql}")
        execute(connection, f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role_sql}")
        execute(connection, f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role_sql}")
        execute(connection, f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {role_sql}")
    for role_sql in (app_sql, review_sql, identity_sql):
        execute(connection, f"GRANT CONNECT ON DATABASE {db_sql} TO {role_sql}")
        execute(connection, f"GRANT USAGE ON SCHEMA public TO {role_sql}")
    grant_many(connection, "SELECT, INSERT, UPDATE, DELETE", APP_RW_TABLES, app_role)
    grant(connection, "SELECT, INSERT", "document_versions", app_role)
    grant(connection, "UPDATE (rescinded_at,state_version)", "document_versions", app_role)
    grant(connection, "SELECT", "corpus_state_epoch", app_role)
    grant(connection, "SELECT, INSERT", "audit_events", app_role)
    grant_many(connection, "SELECT,INSERT,UPDATE", ("audit_anchor_outbox", "audit_heads"), app_role)
    grant_many(connection, "SELECT", REVIEW_SELECT, review_role)
    grant_many(connection, "UPDATE", REVIEW_UPDATE, review_role)
    grant_many(connection, "INSERT", ("audit_events", "audit_anchor_outbox"), review_role)
    grant(connection, "SELECT", "alembic_version", app_role)
    for function in RLS_ACCESSORS:
        grant_execute(connection, function, app_role)
        grant_execute(connection, function, review_role)
    grant_execute(connection, RLS_BINDER, identity_role)
    execute(connection, "REVOKE ALL ON TABLE korpus_rls_identity_bindings FROM PUBLIC")
    for role_sql in (app_sql, review_sql, identity_sql):
        execute(connection, f"ALTER ROLE {role_sql} RESET ALL")
        execute(connection, f"ALTER ROLE {role_sql} IN DATABASE {db_sql} RESET ALL")
        execute(connection, f"ALTER ROLE {role_sql} SET statement_timeout='60s'")
        execute(connection, f"ALTER ROLE {role_sql} SET lock_timeout='5s'")
        execute(connection, f"ALTER ROLE {role_sql} SET idle_in_transaction_session_timeout='60s'")
engine.dispose()
print(f"prepared split roles: app={app_role}, review={review_role}, identity={identity_role}, database={database}")
