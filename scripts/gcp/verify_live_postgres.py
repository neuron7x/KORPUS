#!/usr/bin/env python3
"""Fail-closed production PostgreSQL/RLS acceptance gate.

This gate is intentionally non-destructive. It verifies the migrated schema, role
capabilities, grants and FORCE RLS from two independent connections: the Cloud SQL
admin identity and the exact non-superuser application role used by KORPUS.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from korpus.infrastructure.schema import SCHEMA_REVISION

RLS_TABLES = frozenset(
    {
        "documents",
        "document_versions",
        "document_compartments",
        "evidence_spans",
        "span_embeddings",
        "ingestion_jobs",
    }
)
EXPECTED_POLICY_COMMANDS = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
FORBIDDEN_TABLE_PRIVILEGES = frozenset({"TRUNCATE", "REFERENCES", "TRIGGER"})


def _read_secret(path: str) -> str:
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"empty secret file: {path}")
    return value


def _grant_contract() -> dict[str, set[str]]:
    script = Path(__file__).resolve().parents[1] / "prepare_postgres_role.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.endswith("_TABLES"):
            continue
        values = {
            element.value
            for element in getattr(node.value, "elts", [])
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
        out[target.id] = values
    required = {"READ_WRITE_TABLES", "AUDIT_APPEND_TABLES", "AUDIT_MUTABLE_TABLES"}
    if set(out) != required:
        raise RuntimeError(f"PostgreSQL grant contract is unreadable or drifted: {sorted(out)}")
    return out


def _app_url(admin_url: str, app_role: str, app_password: str) -> str:
    url = make_url(admin_url)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("production PostgreSQL gate requires a PostgreSQL URL")
    return url.set(username=app_role, password=app_password).render_as_string(hide_password=False)


def _expected_grants(contract: dict[str, set[str]]) -> dict[str, set[str]]:
    expected: dict[str, set[str]] = {}
    for table in contract["READ_WRITE_TABLES"]:
        expected[table] = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    for table in contract["AUDIT_APPEND_TABLES"]:
        expected[table] = {"SELECT", "INSERT"}
    for table in contract["AUDIT_MUTABLE_TABLES"]:
        expected[table] = {"SELECT", "INSERT", "UPDATE"}
    expected["alembic_version"] = {"SELECT"}
    return expected


def _collect_admin(conn: Any, app_role: str, expected_grants: dict[str, set[str]]) -> dict[str, Any]:
    return {
        "server_version_num": int(conn.execute(text("SHOW server_version_num")).scalar_one()),
        "database": str(conn.execute(text("SELECT current_database()")) .scalar_one()),
        "schema_revision": conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none(),
        "app_role": conn.execute(
            text(
                "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                "rolinherit, rolbypassrls, rolconnlimit, COALESCE(rolconfig, ARRAY[]::text[]) AS rolconfig "
                "FROM pg_roles WHERE rolname = :role"
            ), {"role": app_role},
        ).mappings().one_or_none(),
        "rls_rows": conn.execute(
            text(
                "SELECT c.relname AS table_name, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relname = ANY(CAST(:tables AS text[]))"
            ), {"tables": sorted(RLS_TABLES)},
        ).mappings().all(),
        "policy_rows": conn.execute(
            text(
                "SELECT tablename, policyname, cmd FROM pg_policies "
                "WHERE schemaname='public' AND tablename = ANY(CAST(:tables AS text[]))"
            ), {"tables": sorted(RLS_TABLES)},
        ).mappings().all(),
        "grant_rows": conn.execute(
            text(
                "SELECT table_name, privilege_type FROM information_schema.table_privileges "
                "WHERE table_schema='public' AND grantee=:role"
            ), {"role": app_role},
        ).mappings().all(),
        "public_grants": conn.execute(
            text(
                "SELECT table_name, privilege_type FROM information_schema.table_privileges "
                "WHERE table_schema='public' AND grantee='PUBLIC' AND table_name = ANY(CAST(:tables AS text[]))"
            ), {"tables": sorted(expected_grants)},
        ).mappings().all(),
        "default_grants_to_app": int(conn.execute(
            text(
                "SELECT COUNT(*) FROM pg_default_acl d "
                "CROSS JOIN LATERAL aclexplode(d.defaclacl) x "
                "JOIN pg_roles r ON r.oid=x.grantee WHERE r.rolname=:role"
            ), {"role": app_role},
        ).scalar_one()),
        "app_schema_create": bool(conn.execute(
            text("SELECT has_schema_privilege(:role, 'public', 'CREATE')"), {"role": app_role},
        ).scalar_one()),
    }


def _expect_denied(conn: Any, sql: str, *, nested: bool = False) -> bool:
    try:
        if nested:
            with conn.begin_nested():
                conn.execute(text(sql))
        else:
            conn.execute(text(sql))
    except DBAPIError:
        conn.rollback()
        return True
    return False


def _collect_app(conn: Any) -> dict[str, Any]:
    counts = {
        table: int(conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one())
        for table in sorted(RLS_TABLES - {"ingestion_jobs"})
    }
    return {
        "app_current_user": str(conn.execute(text("SELECT current_user")).scalar_one()),
        "missing_identity_counts": counts,
        "destructive_denials": {
            "alembic_update_denied": _expect_denied(
                conn, "UPDATE alembic_version SET version_num=version_num", nested=True
            ),
            "set_role_postgres_denied": _expect_denied(conn, "SET ROLE postgres"),
            "disable_rls_denied": _expect_denied(
                conn, "ALTER TABLE documents DISABLE ROW LEVEL SECURITY"
            ),
        },
    }


def _normalized_snapshot(
    admin_snapshot: dict[str, Any], app_snapshot: dict[str, Any], expected_grants: dict[str, set[str]]
) -> dict[str, Any]:
    grants: dict[str, set[str]] = {table: set() for table in expected_grants}
    for row in admin_snapshot.pop("grant_rows"):
        table = str(row["table_name"])
        if table in grants:
            grants[table].add(str(row["privilege_type"]).upper())
    rls = {
        str(row["table_name"]): {
            "enabled": bool(row["relrowsecurity"]), "forced": bool(row["relforcerowsecurity"])
        }
        for row in admin_snapshot.pop("rls_rows")
    }
    policies: dict[str, set[str]] = {table: set() for table in RLS_TABLES}
    for row in admin_snapshot.pop("policy_rows"):
        policies[str(row["tablename"])].add(str(row["cmd"]).upper())
    role = admin_snapshot["app_role"]
    admin_snapshot["app_role"] = dict(role) if role else None
    admin_snapshot["public_grants"] = [dict(row) for row in admin_snapshot["public_grants"]]
    return {
        **admin_snapshot,
        **app_snapshot,
        "rls": rls,
        "policies": {k: sorted(v) for k, v in policies.items()},
        "grants": {k: sorted(v) for k, v in grants.items()},
        "expected_grants": {k: sorted(v) for k, v in expected_grants.items()},
    }


def _collect(admin_url: str, app_url: str, app_role: str) -> dict[str, Any]:
    expected_grants = _expected_grants(_grant_contract())
    admin = create_engine(admin_url, pool_pre_ping=True)
    app = create_engine(app_url, pool_pre_ping=True)
    try:
        with admin.connect() as conn:
            admin_snapshot = _collect_admin(conn, app_role, expected_grants)
        with app.connect() as conn:
            app_snapshot = _collect_app(conn)
        return _normalized_snapshot(admin_snapshot, app_snapshot, expected_grants)
    finally:
        app.dispose()
        admin.dispose()


def _role_capabilities_ok(role: dict[str, Any], app_role: str) -> bool:
    return all((
        role.get("rolname") == app_role,
        role.get("rolcanlogin") is True,
        role.get("rolsuper") is False,
        role.get("rolcreatedb") is False,
        role.get("rolcreaterole") is False,
        role.get("rolinherit") is False,
        role.get("rolbypassrls") is False,
        int(role.get("rolconnlimit", -1)) == 64,
    ))


def _force_rls_complete(rls: dict[str, Any]) -> bool:
    return set(rls) == RLS_TABLES and all(v.get("enabled") and v.get("forced") for v in rls.values())


def _policy_coverage_complete(policies: dict[str, set[str]]) -> bool:
    return set(policies) == RLS_TABLES and all(v == EXPECTED_POLICY_COMMANDS for v in policies.values())


def _grants_exact(expected: dict[str, set[str]], actual: dict[str, set[str]]) -> bool:
    return expected == actual and all(not (v & FORBIDDEN_TABLE_PRIVILEGES) for v in actual.values())


def _missing_identity_denied(counts: dict[str, Any]) -> bool:
    return set(counts) == (RLS_TABLES - {"ingestion_jobs"}) and all(int(v) == 0 for v in counts.values())


def _destructive_actions_denied(denials: dict[str, Any]) -> bool:
    return all(denials.get(key) is True for key in (
        "alembic_update_denied", "disable_rls_denied", "set_role_postgres_denied"
    ))


def evaluate(snapshot: dict[str, Any], app_role: str = "korpus_app") -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    add = lambda i, ok, evidence: checks.append({"id": i, "passed": bool(ok), "evidence": evidence})
    version = int(snapshot.get("server_version_num", 0))
    add("POSTGRES_MAJOR_17", 170000 <= version < 180000, {"server_version_num": version})
    add("POSTGRES_DATABASE", snapshot.get("database") == "korpus", {"database": snapshot.get("database")})
    add("SCHEMA_HEAD", snapshot.get("schema_revision") == SCHEMA_REVISION, {"expected": SCHEMA_REVISION, "actual": snapshot.get("schema_revision")})
    role = snapshot.get("app_role") or {}
    add("APP_ROLE_CAPABILITIES", _role_capabilities_ok(role, app_role), {k: role.get(k) for k in ("rolname","rolcanlogin","rolsuper","rolcreatedb","rolcreaterole","rolinherit","rolbypassrls","rolconnlimit")})
    role_config = {str(x).split("=", 1)[0] for x in role.get("rolconfig", []) if "=" in str(x)}
    add("APP_ROLE_TIMEOUT_DEFAULTS", {"statement_timeout","lock_timeout","idle_in_transaction_session_timeout"} <= role_config, {"configured": sorted(role_config)})
    rls = snapshot.get("rls", {})
    add("FORCE_RLS_ALL_BOUNDARY_TABLES", _force_rls_complete(rls), rls)
    policies = {k: set(v) for k, v in snapshot.get("policies", {}).items()}
    add("RLS_POLICY_COMMAND_COVERAGE", _policy_coverage_complete(policies), {k: sorted(v) for k,v in policies.items()})
    expected = {k: set(v) for k, v in snapshot.get("expected_grants", {}).items()}
    actual = {k: set(v) for k, v in snapshot.get("grants", {}).items()}
    add("APP_TABLE_GRANTS_EXACT", _grants_exact(expected, actual), {"expected": {k:sorted(v) for k,v in expected.items()}, "actual": {k:sorted(v) for k,v in actual.items()}})
    add("NO_PUBLIC_TABLE_GRANTS", snapshot.get("public_grants") == [], snapshot.get("public_grants"))
    add("NO_DEFAULT_GRANT_EXPANSION", snapshot.get("default_grants_to_app") == 0, {"count": snapshot.get("default_grants_to_app")})
    add("APP_CANNOT_CREATE_IN_PUBLIC_SCHEMA", snapshot.get("app_schema_create") is False, {"has_create": snapshot.get("app_schema_create")})
    add("APP_LOGIN_IDENTITY", snapshot.get("app_current_user") == app_role, {"current_user": snapshot.get("app_current_user")})
    counts = snapshot.get("missing_identity_counts", {})
    add("RLS_MISSING_IDENTITY_DENIES_CORPUS", _missing_identity_denied(counts), counts)
    denials = snapshot.get("destructive_denials", {})
    add("APP_CANNOT_MUTATE_SCHEMA_STATE", _destructive_actions_denied(denials), denials)
    return checks


def _redact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="-")
    parser.add_argument("--app-role", default=os.getenv("KORPUS_POSTGRES_APP_ROLE", "korpus_app"))
    args = parser.parse_args()
    admin_url = os.getenv("KORPUS_DATABASE_URL", "")
    app_secret_file = os.getenv("KORPUS_POSTGRES_APP_PASSWORD_FILE", "")
    if not admin_url or not app_secret_file:
        raise SystemExit("KORPUS_DATABASE_URL and KORPUS_POSTGRES_APP_PASSWORD_FILE are required")
    app_url = _app_url(admin_url, args.app_role, _read_secret(app_secret_file))
    snapshot = _collect(admin_url, app_url, args.app_role)
    checks = evaluate(snapshot, args.app_role)
    result = {
        "schema_version": 1,
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "PASS" if all(c["passed"] for c in checks) else "FAIL",
        "checks": checks,
        "snapshot": _redact_snapshot(snapshot),
    }
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output == "-":
        sys.stdout.write(payload)
    else:
        Path(args.output).write_text(payload, encoding="utf-8")
    if result["status"] != "PASS":
        for check in checks:
            if not check["passed"]:
                print(f"FAIL: {check['id']}: {check['evidence']}", file=sys.stderr)
        return 1
    print(f"PASS: PostgreSQL production gate {len(checks)}/{len(checks)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
