from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

APP_URL = os.getenv("KORPUS_POSTGRES_TEST_URL") or os.getenv("KORPUS_TEST_DATABASE_URL")
REVIEW_URL = os.getenv("KORPUS_REVIEW_DATABASE_URL")
IDENTITY_URL = os.getenv("RLS_IDENTITY_DATABASE_URL")
pytestmark = pytest.mark.postgres

RUNTIME = (
    (APP_URL, "korpus_app_runtime"),
    (REVIEW_URL, "korpus_review_runtime"),
    (IDENTITY_URL, "korpus_identity_runtime"),
)
GROUPS = {"korpus_app_runtime", "korpus_review_runtime", "korpus_identity_runtime"}
PROTECTED_TABLES = {
    "documents",
    "document_versions",
    "evidence_spans",
    "span_embeddings",
    "document_compartments",
}
ACCESSORS = (
    "public.korpus_rls_clearance()",
    "public.korpus_rls_corpora()",
    "public.korpus_rls_classifications()",
    "public.korpus_rls_compartments()",
    "public.korpus_rls_roles()",
)
BINDER = (
    "public.korpus_bind_rls_identity(integer,timestamptz,text,text,text,integer,text,text,text,text)"
)


def _engine(url: str):
    return create_engine(url, future=True, pool_pre_ping=True)


def _require(url: str | None) -> str:
    if not url:
        pytest.skip("split PostgreSQL app/review/identity URLs are required")
    return url


@pytest.mark.parametrize(("url", "expected_parent"), RUNTIME)
def test_runtime_login_has_exact_nonexercisable_marker_membership(
    url: str | None, expected_parent: str
) -> None:
    engine = _engine(_require(url))
    try:
        with engine.connect() as connection:
            role = connection.execute(
                text(
                    "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                    "rolinherit, rolreplication, rolbypassrls FROM pg_catalog.pg_roles "
                    "WHERE rolname=current_user"
                )
            ).one()
            memberships = connection.execute(
                text(
                    "SELECT parent.rolname, m.admin_option, m.inherit_option, m.set_option "
                    "FROM pg_catalog.pg_auth_members m "
                    "JOIN pg_catalog.pg_roles parent ON parent.oid=m.roleid "
                    "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                    "WHERE member.rolname=current_user"
                )
            ).all()
            access = connection.execute(
                text(
                    "SELECT pg_catalog.pg_has_role(current_user,:parent,'MEMBER'), "
                    "pg_catalog.pg_has_role(current_user,:parent,'USAGE'), "
                    "pg_catalog.pg_has_role(current_user,:parent,'SET')"
                ),
                {"parent": expected_parent},
            ).one()
        assert role.rolcanlogin is True
        assert role.rolsuper is False
        assert role.rolcreatedb is False
        assert role.rolcreaterole is False
        assert role.rolinherit is False
        assert role.rolreplication is False
        assert role.rolbypassrls is False
        assert len(memberships) == 1
        parent, admin_option, inherit_option, set_option = memberships[0]
        assert str(parent) == expected_parent
        assert admin_option is False
        assert inherit_option is False
        assert set_option is False
        assert tuple(bool(value) for value in access) == (True, False, False)
    finally:
        engine.dispose()


def test_runtime_groups_have_no_parent_memberships_or_database_superpowers() -> None:
    engine = _engine(_require(APP_URL))
    try:
        with engine.connect() as connection:
            roles = connection.execute(
                text(
                    "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                    "rolinherit, rolreplication, rolbypassrls FROM pg_catalog.pg_roles "
                    "WHERE rolname = ANY(:groups) ORDER BY rolname"
                ),
                {"groups": sorted(GROUPS)},
            ).all()
            memberships = connection.execute(
                text(
                    "SELECT member.rolname, parent.rolname FROM pg_catalog.pg_auth_members m "
                    "JOIN pg_catalog.pg_roles parent ON parent.oid=m.roleid "
                    "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                    "WHERE member.rolname = ANY(:groups)"
                ),
                {"groups": sorted(GROUPS)},
            ).all()
        assert {str(role.rolname) for role in roles} == GROUPS
        for role in roles:
            assert role.rolcanlogin is False
            assert role.rolsuper is False
            assert role.rolcreatedb is False
            assert role.rolcreaterole is False
            assert role.rolinherit is False
            assert role.rolreplication is False
            assert role.rolbypassrls is False
        assert memberships == []
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("url", "binder_execute", "accessor_execute"),
    (
        (APP_URL, False, True),
        (REVIEW_URL, False, True),
        (IDENTITY_URL, True, False),
    ),
)
def test_runtime_function_acl_is_exact(
    url: str | None, binder_execute: bool, accessor_execute: bool
) -> None:
    engine = _engine(_require(url))
    try:
        with engine.connect() as connection:
            binder = connection.execute(
                text(
                    "SELECT pg_catalog.has_function_privilege("
                    "current_user, pg_catalog.to_regprocedure(:signature), 'EXECUTE')"
                ),
                {"signature": BINDER},
            ).scalar_one()
            accessors = [
                bool(
                    connection.execute(
                        text(
                            "SELECT pg_catalog.has_function_privilege("
                            "current_user, pg_catalog.to_regprocedure(:signature), 'EXECUTE')"
                        ),
                        {"signature": signature},
                    ).scalar_one()
                )
                for signature in ACCESSORS
            ]
        assert bool(binder) is binder_execute
        assert accessors == [accessor_execute] * len(ACCESSORS)
    finally:
        engine.dispose()


@pytest.mark.parametrize("url", [APP_URL, REVIEW_URL, IDENTITY_URL])
def test_no_runtime_login_has_direct_binding_table_privilege(url: str | None) -> None:
    engine = _engine(_require(url))
    try:
        with engine.connect() as connection:
            privileges = connection.execute(
                text(
                    "SELECT "
                    "pg_catalog.has_table_privilege(current_user, 'public.korpus_rls_identity_bindings', 'SELECT'), "
                    "pg_catalog.has_table_privilege(current_user, 'public.korpus_rls_identity_bindings', 'INSERT'), "
                    "pg_catalog.has_table_privilege(current_user, 'public.korpus_rls_identity_bindings', 'UPDATE'), "
                    "pg_catalog.has_table_privilege(current_user, 'public.korpus_rls_identity_bindings', 'DELETE')"
                )
            ).one()
        assert tuple(bool(value) for value in privileges) == (False, False, False, False)
    finally:
        engine.dispose()


def test_identity_broker_has_no_direct_protected_data_plane_privileges() -> None:
    engine = _engine(_require(IDENTITY_URL))
    try:
        with engine.connect() as connection:
            for table in sorted(PROTECTED_TABLES):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    allowed = connection.execute(
                        text(
                            "SELECT pg_catalog.has_table_privilege("
                            "current_user, :table, :privilege)"
                        ),
                        {"table": f"public.{table}", "privilege": privilege},
                    ).scalar_one()
                    assert allowed is False, f"identity broker unexpectedly has {privilege} on {table}"
    finally:
        engine.dispose()


def test_security_definer_routines_have_hardened_search_path_and_nonruntime_owner() -> None:
    engine = _engine(_require(APP_URL))
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT p.proname, p.prosecdef, p.proconfig, owner.rolname "
                    "FROM pg_catalog.pg_proc p "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
                    "JOIN pg_catalog.pg_roles owner ON owner.oid=p.proowner "
                    "WHERE n.nspname='public' AND p.proname = ANY(:names) "
                    "ORDER BY p.proname"
                ),
                {
                    "names": [
                        "korpus_bind_rls_identity",
                        "korpus_rls_clearance",
                        "korpus_rls_corpora",
                        "korpus_rls_classifications",
                        "korpus_rls_compartments",
                        "korpus_rls_roles",
                    ]
                },
            ).all()
        assert len(rows) == 6
        runtime_owners = {"korpus_app", "korpus_review", "korpus_identity"} | GROUPS
        for _name, security_definer, config, owner in rows:
            assert security_definer is True
            assert config is not None and "search_path=pg_catalog" in set(config)
            assert str(owner) not in runtime_owners
    finally:
        engine.dispose()
