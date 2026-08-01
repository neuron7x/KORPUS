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
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
GOVERNED_TABLES = {
    "documents",
    "document_versions",
    "evidence_spans",
    "span_embeddings",
    "document_compartments",
}


def validate_payload(payload: dict[str, object]) -> list[str]:
    failures = [f"missing:{name}" for name in sorted(set(REQUIRED) - payload.keys())]
    verdict = payload.get("verdict")
    if verdict not in {"PASS", "PASS_WITH_CAVEATS", "FAIL"}:
        failures.append("invalid:verdict")
    if payload.get("production_authorized") is not False:
        failures.append("invalid:production_authorized")
    if payload.get("schema") != "korpus.postgres-live-assurance.v1":
        failures.append("invalid:schema")
    if payload.get("act_id") != "KORPUS-ACT-01":
        failures.append("invalid:act-id")
    if any(
        not COMMIT_SHA.fullmatch(str(payload.get(name, "")))
        for name in ("base_commit", "candidate_commit")
    ):
        failures.append("invalid:commit-provenance")
    if re.search(r"postgres(?:ql)?://[^/\s]*:[^@\s]*@", json.dumps(payload)):
        failures.append("secret:credential-bearing-url")
    if failures or verdict == "FAIL":
        return failures

    role = payload.get("application_role_properties", {})
    if not isinstance(role, dict) or any(
        role.get(name) is not False
        for name in (
            "rolsuper",
            "rolbypassrls",
            "rolcreatedb",
            "rolcreaterole",
            "rolinherit",
            "schema_create",
            "database_create",
        )
    ) or role.get("governed_table_ownership_count") != 0:
        failures.append("predicate:application-role")
    expected = payload.get("alembic_expected_heads")
    if not isinstance(expected, list) or len(expected) != 1 or not expected[0]:
        failures.append("predicate:expected-head")
    if payload.get("source_database_revision") != expected:
        failures.append("predicate:source-revision")
    if payload.get("restored_database_revision") != expected:
        failures.append("predicate:restored-revision")
    rls = payload.get("rls_cases", {})
    missing_counts = rls.get("missing_context_counts", {}) if isinstance(rls, dict) else {}
    if set(missing_counts) != GOVERNED_TABLES or any(
        value != 0 for value in missing_counts.values()
    ):
        failures.append("predicate:missing-context")
    if (
        not isinstance(rls, dict)
        or not isinstance(rls.get("public_identity_public_rows"), int)
        or isinstance(rls.get("public_identity_public_rows"), bool)
        or rls.get("public_identity_public_rows", 0) <= 0
        or rls.get("public_identity_restricted_rows") != 0
    ):
        failures.append("predicate:cross-corpus")
    compartments = payload.get("compartment_cases")
    if compartments != {"missing": 0, "unrelated": 0, "exact": 1}:
        failures.append("predicate:compartment-isolation")
    policies = payload.get("table_policy_inventory")
    if not isinstance(policies, list) or any(
        not isinstance(policy, dict) for policy in policies
    ):
        failures.append("predicate:policy-inventory")
    else:
        protected_tables = {
            str(policy.get("tablename"))
            for policy in policies
            if policy.get("schemaname") == "public"
            and policy.get("cmd") == "SELECT"
            and policy.get("rls_enabled") is True
            and policy.get("force_rls") is True
        }
        if not GOVERNED_TABLES.issubset(protected_tables):
            failures.append("predicate:policy-inventory")
    grants = payload.get("grant_inventory")
    if not isinstance(grants, list) or not grants or any(
        not isinstance(grant, dict)
        or set(grant) != {"table_name", "privilege_type"}
        or grant.get("privilege_type") not in {"SELECT", "INSERT", "UPDATE", "DELETE"}
        or (
            grant.get("table_name") == "alembic_version"
            and grant.get("privilege_type") != "SELECT"
        )
        for grant in grants
    ):
        failures.append("predicate:grant-inventory")
    ddl = payload.get("ddl_denial_cases", {})
    required_ddl = {
        "alembic_update",
        "create_table",
        "alter_table",
        "drop_table",
        "create_policy",
        "create_schema",
        "create_extension",
        "create_role",
        "alter_role",
        "set_role",
    }
    if (
        not isinstance(ddl, dict)
        or set(ddl) != required_ddl
        or any(value != "PASS" for value in ddl.values())
    ):
        failures.append("predicate:ddl-denial")
    backup = payload.get("backup", {})
    if not isinstance(backup, dict) or not (
        backup.get("encrypted") is True
        and backup.get("manifest_verified") is True
        and backup.get("cipher") == "AES-256-GCM"
    ):
        failures.append("predicate:backup")
    restore = payload.get("restore", {})
    durations = (
        backup.get("duration_seconds") if isinstance(backup, dict) else None,
        restore.get("duration_seconds") if isinstance(restore, dict) else None,
        restore.get("verification_seconds") if isinstance(restore, dict) else None,
    )
    total = restore.get("total_recovery_seconds") if isinstance(restore, dict) else None
    numeric_durations = [
        float(value)
        for value in durations
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
    ]
    if (
        not isinstance(restore, dict)
        or restore.get("measurement") != "ANCHORED"
        or len(numeric_durations) != len(durations)
        or not isinstance(total, (int, float))
        or isinstance(total, bool)
        or total <= 0
        or abs(total - sum(numeric_durations)) > 1e-9
    ):
        failures.append("predicate:recovery-timing")
    pytest_result = payload.get("pytest", {})
    if (
        not isinstance(pytest_result, dict)
        or pytest_result.get("live_postgres") != "PASS"
        or not isinstance(pytest_result.get("tests"), int)
        or pytest_result.get("tests", 0) <= 0
        or pytest_result.get("failures") != 0
        or pytest_result.get("errors") != 0
        or pytest_result.get("skipped") != 0
    ):
        failures.append("predicate:pytest")
    mutation = payload.get("mutation")
    if mutation is not None and (
        not isinstance(mutation, dict)
        or mutation.get("status") not in {"PASS", "UNAVAILABLE"}
        or (
            mutation.get("status") == "PASS"
            and (
                not isinstance(mutation.get("mutants"), int)
                or mutation.get("mutants", 0) <= 0
                or mutation.get("killed") != mutation.get("mutants")
                or mutation.get("candidate_commit") != payload.get("candidate_commit")
                or not DIGEST.fullmatch(str(mutation.get("sha256", "")))
            )
        )
    ):
        failures.append("predicate:mutation")
    source_digest = str(payload.get("source_state_digest", ""))
    restored_digest = str(payload.get("restored_state_digest", ""))
    if (
        not DIGEST.fullmatch(source_digest)
        or source_digest != restored_digest
    ):
        failures.append("predicate:state-digest")
    iam = payload.get("iam_006_probe")
    if not isinstance(iam, dict):
        failures.append("predicate:iam-006")
    else:
        broadened = iam.get("broadened_restricted_rows")
        status = iam.get("status")
        independent = iam.get("trust_anchor_independent_of_application")
        consistent_open = (
            status == "CONFIRMED_OPEN"
            and isinstance(broadened, int)
            and not isinstance(broadened, bool)
            and broadened > 0
            and independent is False
        )
        consistent_not_reproduced = (
            status == "NOT_REPRODUCED"
            and broadened == 0
            and isinstance(independent, bool)
        )
        if isinstance(rls, dict) and rls.get(
            "cross_corpus_direct_sql_restricted_rows"
        ) != broadened:
            failures.append("predicate:iam-006")
        if not (consistent_open or consistent_not_reproduced):
            failures.append("predicate:iam-006")
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
