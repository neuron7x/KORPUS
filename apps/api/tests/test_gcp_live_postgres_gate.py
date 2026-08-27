from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "scripts/gcp/verify_live_postgres.py"
spec = importlib.util.spec_from_file_location("verify_live_postgres", PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def good_snapshot():
    expected = {k: sorted(v) for k, v in mod._expected_grants(mod._grant_contract()).items()}
    return {
        "server_version_num": 170006,
        "database": "korpus",
        "schema_revision": mod.SCHEMA_REVISION,
        "app_role": {
            "rolname": "korpus_app",
            "rolcanlogin": True,
            "rolsuper": False,
            "rolcreatedb": False,
            "rolcreaterole": False,
            "rolinherit": False,
            "rolbypassrls": False,
            "rolconnlimit": 64,
            "rolconfig": [
                "statement_timeout=60s",
                "lock_timeout=5s",
                "idle_in_transaction_session_timeout=60s",
            ],
        },
        "rls": {table: {"enabled": True, "forced": True} for table in mod.RLS_TABLES},
        "policies": {table: sorted(mod.EXPECTED_POLICY_COMMANDS) for table in mod.RLS_TABLES},
        "grants": copy.deepcopy(expected),
        "expected_grants": expected,
        "public_grants": [],
        "default_grants_to_app": 0,
        "app_schema_create": False,
        "app_current_user": "korpus_app",
        "missing_identity_counts": {table: 0 for table in mod.RLS_TABLES - {"ingestion_jobs"}},
        "destructive_denials": {
            "alembic_update_denied": True,
            "set_role_postgres_denied": True,
            "disable_rls_denied": True,
        },
    }


def status(snapshot):
    return {x["id"]: x["passed"] for x in mod.evaluate(snapshot)}


def test_valid_live_postgres_snapshot_passes_all_predicates():
    result = status(good_snapshot())
    assert result and all(result.values()), [k for k, v in result.items() if not v]


def test_bypassrls_role_mutation_is_killed():
    x = good_snapshot()
    x["app_role"]["rolbypassrls"] = True
    assert status(x)["APP_ROLE_CAPABILITIES"] is False


def test_force_rls_mutation_is_killed():
    x = good_snapshot()
    x["rls"]["documents"]["forced"] = False
    assert status(x)["FORCE_RLS_ALL_BOUNDARY_TABLES"] is False


def test_grant_expansion_mutation_is_killed():
    x = good_snapshot()
    x["grants"]["audit_events"].append("UPDATE")
    assert status(x)["APP_TABLE_GRANTS_EXACT"] is False


def test_missing_identity_visibility_mutation_is_killed():
    x = good_snapshot()
    x["missing_identity_counts"]["documents"] = 1
    assert status(x)["RLS_MISSING_IDENTITY_DENIES_CORPUS"] is False


def test_schema_revision_drift_is_killed():
    x = good_snapshot()
    x["schema_revision"] = "old"
    assert status(x)["SCHEMA_HEAD"] is False


def test_schema_mutation_capability_is_killed():
    x = good_snapshot()
    x["destructive_denials"]["disable_rls_denied"] = False
    assert status(x)["APP_CANNOT_MUTATE_SCHEMA_STATE"] is False
