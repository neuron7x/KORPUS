"""Стан політик RLS у схемі — питання ДО БАЗИ, не до коду, який її будував.

Портовано з GitHub-лінії 01.09.2026 як ВЛАСТИВОСТІ, а не як реалізація: тамтешній
брокер зветься `korpus_bind_rls_identity` і має іншу сигнатуру, а тутешній —
`korpus_bind_rls_context` і покриває на одну таблицю та один claim більше. Дві
реалізації однієї межі — це знову дві тотожності одного предмета; лишається одна,
та, що доведена запуском на цьому дереві.

Найважливіший тут — `test_no_policy_still_consumes_a_caller_settable_claim`. Міграція
0020 переписала політики шести таблиць; питання «чи ЖОДНА не лишилась на
`current_setting`» не про намір міграції, а про підсумковий стан каталогу. Одна
пропущена таблиця означала б межу, дірку в якій ніхто б не побачив: усі інші тести
зелені, бо перевіряють ті таблиці, які переписано.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL") or os.getenv("KORPUS_TEST_DATABASE_URL")
AUTHZ_URL = os.getenv("KORPUS_AUTHZ_DATABASE_URL")
pytestmark = pytest.mark.postgres

#: Шість, не п'ять: `ingestion_jobs` теж під RLS у цій лінії, і саме її GitHub-лінія
#: не боронила. Список тут ЯВНИЙ, бо виведений із коду список звірявся б сам із собою.
PROTECTED_TABLES = {
    "documents",
    "document_versions",
    "evidence_spans",
    "span_embeddings",
    "document_compartments",
    "ingestion_jobs",
}
CLAIM_ACCESSORS = (
    "korpus_rls_subject",
    "korpus_rls_clearance",
    "korpus_rls_corpora",
    "korpus_rls_classifications",
    "korpus_rls_compartments",
    "korpus_rls_roles",
)
RUNTIME_ROLE_NAMES = {"korpus_app", "korpus_authz"}


def _engine(url: str | None):
    if not url:
        pytest.skip("least-privilege PostgreSQL app URL is required")
    return create_engine(url, future=True, pool_pre_ping=True)


def test_every_protected_table_has_rls_enabled_and_forced() -> None:
    """`ENABLE` без `FORCE` не діє на власника таблиці — і мовчки."""
    engine = _engine(APP_URL)
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
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                    "pg_catalog.pg_get_userbyid(c.relowner) AS owner "
                    "FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relname = ANY(:tables)"
                ),
                {"tables": sorted(PROTECTED_TABLES)},
            ).all()
        assert role.rolsuper is False
        assert role.rolbypassrls is False
        observed = {
            str(name): (bool(enabled), bool(forced), str(owner))
            for name, enabled, forced, owner in rows
        }
        assert set(observed) == PROTECTED_TABLES
        assert all(state[:2] == (True, True) for state in observed.values()), observed
        # Власник таблиці не сміє бути жодним із рантайм-логінів: власника RLS
        # не стримує навіть під FORCE, якщо він же й виконує запит.
        assert all(state[2] not in RUNTIME_ROLE_NAMES for state in observed.values()), observed
    finally:
        engine.dispose()


def test_no_policy_still_consumes_a_caller_settable_claim() -> None:
    """Повнота міграції 0020, поставлена як питання до КАТАЛОГУ, а не до наміру."""
    engine = _engine(APP_URL)
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
        assert all(count == 4 for count in by_table.values()), by_table
        rendered = "\n".join(policy_sql)
        assert "current_setting('korpus." not in rendered, rendered
        for accessor in CLAIM_ACCESSORS:
            assert accessor in rendered, accessor
    finally:
        engine.dispose()


def test_the_application_login_cannot_disable_or_rewrite_a_policy() -> None:
    """Межа, яку можна вимкнути тим самим логіном, від якого вона боронить, — не межа."""
    engine = _engine(APP_URL)
    try:
        for statement in (
            "ALTER TABLE documents DISABLE ROW LEVEL SECURITY",
            "ALTER TABLE documents NO FORCE ROW LEVEL SECURITY",
            "DROP POLICY document_select ON documents",
            "CREATE POLICY korpus_probe_policy ON documents FOR SELECT USING (true)",
            "ALTER TABLE documents OWNER TO CURRENT_USER",
        ):
            with engine.begin() as connection, pytest.raises(Exception) as raised:
                connection.execute(text(statement))
            assert "must be owner" in str(raised.value) or "permission denied" in str(raised.value)
    finally:
        engine.dispose()


def test_the_broker_login_has_no_privilege_on_the_protected_data_plane() -> None:
    """Брокер кладе claim'и; читати документи він не мусить уміти взагалі."""
    engine = _engine(AUTHZ_URL)
    try:
        with engine.connect() as connection:
            granted = connection.execute(
                text(
                    "SELECT c.relname, p.privilege_type "
                    "FROM information_schema.table_privileges p "
                    "JOIN pg_catalog.pg_class c ON c.relname = p.table_name "
                    "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname='public' AND p.grantee = current_user "
                    "AND p.table_name = ANY(:tables)"
                ),
                {"tables": sorted(PROTECTED_TABLES)},
            ).all()
        assert granted == [], granted
    finally:
        engine.dispose()


def test_security_definer_routines_keep_a_hardened_search_path() -> None:
    """`SECURITY DEFINER` без прибитого `search_path` — це підміна об'єктів у чужій схемі."""
    engine = _engine(APP_URL)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT p.proname, p.prosecdef, "
                    "COALESCE(array_to_string(p.proconfig, ','), ''), "
                    "pg_catalog.pg_get_userbyid(p.proowner) AS owner "
                    "FROM pg_catalog.pg_proc p "
                    "JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname='public' AND p.proname LIKE 'korpus\\_%'"
                )
            ).all()
        definers = [row for row in rows if bool(row[1])]
        assert definers, rows
        for name, _secdef, config, owner in definers:
            assert "search_path=" in str(config), (name, config)
            assert str(owner) not in RUNTIME_ROLE_NAMES, (name, owner)
    finally:
        engine.dispose()


def test_the_application_login_may_execute_readers_but_never_the_binder() -> None:
    """Точний ACL: читачі claim'ів — так, брокерська функція — ні. Обидва боки виміряні."""
    engine = _engine(APP_URL)
    try:
        with engine.connect() as connection:
            for accessor in CLAIM_ACCESSORS:
                allowed = connection.execute(
                    text("SELECT has_function_privilege(current_user, :fn, 'EXECUTE')"),
                    {"fn": f"public.{accessor}()"},
                ).scalar_one()
                assert allowed is True, accessor
            binder = connection.execute(
                text("SELECT has_function_privilege(current_user, :fn, 'EXECUTE')"),
                {
                    "fn": "public.korpus_bind_rls_context"
                    "(integer,bigint,name,text,integer,jsonb,jsonb,jsonb,jsonb)"
                },
            ).scalar_one()
            assert binder is False
    finally:
        engine.dispose()
