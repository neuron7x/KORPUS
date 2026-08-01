#!/usr/bin/env python3
"""Deterministically validate required live-assurance evidence fields."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REQUIRED = [
    "schema",
    "act_id",
    "base_commit",
    "candidate_commit",
    "started_at_utc",
    "finished_at_utc",
    "environment",
    "postgres_server_version",
    "pgvector_version",
    "alembic_expected_heads",
    "source_database_revision",
    "restored_database_revision",
    "application_role_properties",
    "table_policy_inventory",
    "grant_inventory",
    "rls_cases",
    "compartment_cases",
    "ddl_denial_cases",
    "backup",
    "restore",
    "source_state_digest",
    "restored_state_digest",
    "pytest",
    "iam_006_probe",
    "unexecuted_gates",
    "production_authorized",
    "verdict",
]


def validate_payload(payload: dict[str, object]) -> list[str]:
    failures = [f"missing:{name}" for name in sorted(set(REQUIRED) - payload.keys())]
    verdict = payload.get("verdict")
    if verdict not in {"PASS", "PASS_WITH_CAVEATS", "FAIL"}:
        failures.append("invalid:verdict")
    if payload.get("production_authorized") is not False:
        failures.append("invalid:production_authorized")
    if re.search(r"postgres(?:ql)?://[^/\s]*:[^@\s]*@", json.dumps(payload)):
        failures.append("secret:credential-bearing-url")
    if failures or verdict == "FAIL":
        return failures

    role = payload.get("application_role_properties", {})
    if not isinstance(role, dict) or any(
        role.get(name) is not False
        for name in ("rolsuper", "rolbypassrls", "rolcreatedb", "rolcreaterole", "rolinherit")
    ):
        failures.append("predicate:application-role")
    expected = payload.get("alembic_expected_heads")
    if payload.get("source_database_revision") != expected:
        failures.append("predicate:source-revision")
    if payload.get("restored_database_revision") != expected:
        failures.append("predicate:restored-revision")
    rls = payload.get("rls_cases", {})
    missing_counts = rls.get("missing_context_counts", {}) if isinstance(rls, dict) else {}
    if not missing_counts or any(value != 0 for value in missing_counts.values()):
        failures.append("predicate:missing-context")
    ddl = payload.get("ddl_denial_cases", {})
    if not isinstance(ddl, dict) or any(
        ddl.get(name) != "PASS" for name in ("alembic_update", "privileged_ddl")
    ):
        failures.append("predicate:ddl-denial")
    backup = payload.get("backup", {})
    if not isinstance(backup, dict) or not (
        backup.get("encrypted") is True
        and backup.get("manifest_verified") is True
        and backup.get("cipher") == "AES-256-GCM"
    ):
        failures.append("predicate:backup")
    pytest_result = payload.get("pytest", {})
    if not isinstance(pytest_result, dict) or pytest_result.get("live_postgres") != "PASS":
        failures.append("predicate:pytest")
    if payload.get("source_state_digest") != payload.get("restored_state_digest"):
        failures.append("predicate:state-digest")
    return failures


def main() -> int:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("invalid postgres assurance evidence; root must be object")
    failures = validate_payload(payload)
    if failures:
        raise SystemExit(f"invalid postgres assurance evidence; failures={failures}")
    print("postgres assurance evidence schema valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
