from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL") or os.getenv("KORPUS_TEST_DATABASE_URL")
pytestmark = pytest.mark.postgres

PROTECTED_TABLES = {
    "documents",
    "document_versions",
    "evidence_spans",
    "span_embeddings",
    "document_compartments",
}


def test_final_postgres_schema_keeps_all_corpus_rls_enabled_and_forced() -> None:
    if not APP_URL:
        pytest.skip("least-privilege PostgreSQL app URL is required")
    engine = create_engine(APP_URL, future=True, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            role = connection.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls "
                    "FROM pg_catalog.pg_roles WHERE rolname=current_user"
                )
            ).one()
            rows = connection.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relname = ANY(:tables)"
                ),
                {"tables": sorted(PROTECTED_TABLES)},
            ).all()
        assert role.rolsuper is False
        assert role.rolbypassrls is False
        observed = {str(name): (bool(enabled), bool(forced)) for name, enabled, forced in rows}
        assert set(observed) == PROTECTED_TABLES
        assert all(state == (True, True) for state in observed.values())
    finally:
        engine.dispose()


def test_final_rls_policies_do_not_consume_legacy_caller_settable_claims() -> None:
    if not APP_URL:
        pytest.skip("least-privilege PostgreSQL app URL is required")
    engine = create_engine(APP_URL, future=True, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT tablename, policyname, COALESCE(qual,''), COALESCE(with_check,'') "
                    "FROM pg_catalog.pg_policies "
                    "WHERE schemaname='public' AND tablename = ANY(:tables) "
                    "ORDER BY tablename, policyname"
                ),
                {"tables": sorted(PROTECTED_TABLES)},
            ).all()
        by_table: dict[str, int] = {name: 0 for name in PROTECTED_TABLES}
        policy_sql: list[str] = []
        for table, _policy, qual, check in rows:
            by_table[str(table)] += 1
            policy_sql.extend((str(qual), str(check)))
        assert all(count == 4 for count in by_table.values())
        rendered = "\n".join(policy_sql)
        assert "current_setting('korpus." not in rendered
        assert "korpus_rls_clearance" in rendered
        assert "korpus_rls_corpora" in rendered
        assert "korpus_rls_classifications" in rendered
        assert "korpus_rls_compartments" in rendered
        assert "korpus_rls_roles" in rendered
    finally:
        engine.dispose()
