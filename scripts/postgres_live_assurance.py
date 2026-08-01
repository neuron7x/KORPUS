#!/usr/bin/env python3
"""Emit sanitized machine evidence for the live PostgreSQL assurance boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from alembic_state import database_revisions, expected_heads, verify_revisions
from backup_crypto import load_key
from backup_manifest import sign, validate_fields
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

ROOT = Path(__file__).resolve().parents[1]
TABLES = (
    "documents",
    "document_versions",
    "evidence_spans",
    "span_embeddings",
    "document_compartments",
    "audit_heads",
    "audit_events",
)
GOVERNED_TABLES = TABLES[:5]
DDL_PROBES = {
    "create_table": "CREATE TABLE app_role_must_not_create(id integer)",
    "alter_table": "ALTER TABLE documents ADD COLUMN app_role_must_not_add integer",
    "drop_table": "DROP TABLE documents",
    "create_policy": "CREATE POLICY app_role_must_not_create ON documents USING (true)",
    "create_schema": "CREATE SCHEMA app_role_must_not_create",
    "create_extension": "CREATE EXTENSION pg_trgm",
    "create_role": "CREATE ROLE app_role_must_not_create",
    "alter_role": "ALTER ROLE postgres NOLOGIN",
    "set_role": "SET ROLE postgres",
}
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


def candidate_commit() -> str:
    """Resolve immutable provenance without assuming Git exists in the gate image."""
    value = os.getenv("KORPUS_CANDIDATE_COMMIT") or os.getenv("CI_COMMIT_SHA")
    if value is None:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    if not COMMIT_SHA.fullmatch(value):
        raise ValueError("candidate commit must be a full lowercase Git SHA-1")
    return value


def ddl_denial_receipt(engine: Engine) -> dict[str, str]:
    receipt: dict[str, str] = {}
    for identifier, statement in DDL_PROBES.items():
        try:
            with engine.begin() as connection:
                connection.execute(text(statement))
            receipt[identifier] = "FAIL"
        except DBAPIError:
            receipt[identifier] = "PASS"
    return receipt


def security_predicates_pass(
    role: dict[str, object],
    compartment_cases: dict[str, int],
    policies: list[dict[str, object]],
    public_rows: int,
    public_restricted_rows: int,
) -> bool:
    """Evaluate the security receipt independently from report serialization."""
    role_denials = (
        "rolsuper",
        "rolbypassrls",
        "rolcreatedb",
        "rolcreaterole",
        "rolinherit",
        "schema_create",
        "database_create",
    )
    return all(
        (
            all(role.get(name) is False for name in role_denials),
            role.get("governed_table_ownership_count") == 0,
            public_rows > 0,
            public_restricted_rows == 0,
            compartment_cases == {"missing": 0, "unrelated": 0, "exact": 1},
            all(
                any(
                    policy.get("tablename") == table
                    and policy.get("cmd") == "SELECT"
                    and policy.get("rls_enabled") is True
                    and policy.get("force_rls") is True
                    for policy in policies
                )
                for table in GOVERNED_TABLES
            ),
        )
    )


def safe_url(name: str) -> str:
    value = os.environ[name]
    return value.replace("postgresql://", "postgresql+psycopg://", 1)


def state_digest(url: str) -> tuple[str, dict[str, int]]:
    engine = create_engine(url)
    payload: dict[str, list[dict[str, object]]] = {}
    counts: dict[str, int] = {}
    with engine.connect() as connection:
        for table in TABLES:
            rows = connection.execute(
                text(f'SELECT row_to_json(t)::text FROM (SELECT * FROM "{table}") t')
            ).scalars()
            normalized = sorted(
                (json.loads(row) for row in rows), key=lambda item: json.dumps(item, sort_keys=True)
            )
            payload[table] = normalized
            counts[table] = len(normalized)
    engine.dispose()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest(), counts


def pytest_receipt(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    totals = {
        name: sum(int(suite.attrib.get(name, "0")) for suite in suites)
        for name in ("tests", "failures", "errors", "skipped")
    }
    status = (
        "PASS"
        if totals["tests"] > 0
        and totals["failures"] == 0
        and totals["errors"] == 0
        and totals["skipped"] == 0
        else "FAIL"
    )
    return {"live_postgres": status, **totals, "receipt": path.name}


def backup_receipt(path: Path, key_file: Path, key_id: str) -> dict[str, object]:
    manifest_path = Path(f"{path}.json")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("backup manifest is not an object")
    validate_fields(payload, expected_file=path.name, expected_key_id=key_id)
    encrypted_digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            encrypted_digest.update(chunk)
    if encrypted_digest.hexdigest() != payload["sha256"]:
        raise ValueError("encrypted backup checksum mismatch")
    if path.stat().st_size != payload["bytes"]:
        raise ValueError("encrypted backup size mismatch")
    if not hmac.compare_digest(
        str(payload["manifest_hmac_sha256"]), sign(payload, load_key(key_file))
    ):
        raise ValueError("backup manifest authentication failed")
    return {
        "encrypted": payload["encrypted"],
        "cipher": payload["cipher"],
        "manifest_verified": True,
        "encrypted_sha256": payload["sha256"],
        "encrypted_bytes": payload["bytes"],
        "plaintext_sha256": payload["plaintext_sha256"],
        "plaintext_bytes": payload["plaintext_bytes"],
        "key_id": payload["key_id"],
        "manifest": manifest_path.name,
    }


def mutation_receipt(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("mutation report is not an object")
    required = ("mutants", "valid_mutants", "killed")
    if any(not isinstance(payload.get(name), int) for name in required):
        raise ValueError("mutation report counts are invalid")
    passed = (
        payload.get("mutation_score") == 1.0
        and payload["mutants"] > 0
        and payload["valid_mutants"] == payload["mutants"]
        and payload["killed"] == payload["mutants"]
        and payload.get("survived") == []
        and payload.get("invalid") == []
    )
    if not passed:
        raise ValueError("mutation report does not prove complete mutant killing")
    return {
        "status": "PASS",
        "mutants": payload["mutants"],
        "killed": payload["killed"],
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def optional_duration(name: str) -> float | None:
    value = os.getenv(name)
    if value is None:
        return None
    duration = float(value)
    if duration <= 0:
        raise ValueError(f"{name} must be positive")
    return duration


def main() -> int:
    started = datetime.now(UTC)
    source_admin = safe_url("KORPUS_SOURCE_ADMIN_URL")
    restored_admin = safe_url("KORPUS_RESTORED_ADMIN_URL")
    app_url = safe_url("KORPUS_POSTGRES_TEST_URL")
    heads = expected_heads()
    source_revision = verify_revisions(database_revisions(source_admin))
    restored_revision = verify_revisions(database_revisions(restored_admin))
    source_digest, source_counts = state_digest(source_admin)
    restored_digest, restored_counts = state_digest(restored_admin)
    app = create_engine(app_url)
    with app.begin() as connection:
        role = (
            connection.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolinherit, "
                    "has_schema_privilege(current_user,'public','CREATE') AS schema_create, "
                    "has_database_privilege(current_user,current_database(),'CREATE') "
                    "AS database_create, "
                    "(SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE n.nspname='public' "
                    "AND c.relname = ANY(:tables) "
                    "AND pg_get_userbyid(c.relowner)=current_user) "
                    "AS governed_table_ownership_count "
                    "FROM pg_roles WHERE rolname=current_user"
                )
                ,
                {"tables": list(TABLES[:5])},
            )
            .mappings()
            .one()
        )
        missing = {
            table: connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
            for table in TABLES[:5]
        }
        for key, value in (
            ("roles", "user"),
            ("clearance", "0"),
            ("corpora", "public"),
            ("classifications", "public"),
            ("compartments", ""),
        ):
            connection.execute(
                text("SELECT set_config(:key,:value,true)"),
                {"key": f"korpus.{key}", "value": value},
            )
        public_rows = connection.execute(
            text("SELECT count(*) FROM documents WHERE corpus_id='public'")
        ).scalar_one()
        public_restricted_rows = connection.execute(
            text("SELECT count(*) FROM documents WHERE corpus_id='restricted-demo'")
        ).scalar_one()
        for key, value in (
            ("roles", "admin,user"),
            ("clearance", "3"),
            ("corpora", "public,restricted-demo"),
            ("classifications", "public,restricted"),
            ("compartments", ""),
        ):
            connection.execute(
                text("SELECT set_config(:key,:value,true)"),
                {"key": f"korpus.{key}", "value": value},
            )
        broadened = connection.execute(
            text("SELECT count(*) FROM documents WHERE corpus_id='restricted-demo'")
        ).scalar_one()
    compartment_cases = {}
    for label, compartments in (("missing", ""), ("unrelated", "other"), ("exact", "omega")):
        with app.begin() as connection:
            for key, value in (
                ("roles", "user"),
                ("clearance", "3"),
                ("corpora", "restricted-demo"),
                ("classifications", "restricted"),
                ("compartments", compartments),
            ):
                connection.execute(
                    text("SELECT set_config(:key,:value,true)"),
                    {"key": f"korpus.{key}", "value": value},
                )
            compartment_cases[label] = connection.execute(
                text("SELECT count(*) FROM documents WHERE compartments_json LIKE '%omega%'")
            ).scalar_one()
    ddl_denials = ddl_denial_receipt(app)
    try:
        with app.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num=version_num"))
        alembic_update_denied = False
    except DBAPIError:
        alembic_update_denied = True
    app.dispose()
    admin = create_engine(source_admin)
    with admin.connect() as connection:
        policies = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT p.schemaname,p.tablename,p.policyname,p.cmd,p.roles,p.qual,"
                    "p.with_check,c.relrowsecurity AS rls_enabled,"
                    "c.relforcerowsecurity AS force_rls "
                    "FROM pg_policies p JOIN pg_namespace n ON n.nspname=p.schemaname "
                    "JOIN pg_class c ON c.relnamespace=n.oid AND c.relname=p.tablename "
                    "WHERE p.schemaname='public' "
                    "ORDER BY tablename,policyname"
                )
            ).mappings()
        ]
        grants = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT table_name,privilege_type "
                    "FROM information_schema.role_table_grants WHERE grantee=:role "
                    "ORDER BY table_name,privilege_type"
                ),
                {"role": os.environ["KORPUS_POSTGRES_APP_ROLE"]},
            ).mappings()
        ]
        server_version = connection.execute(text("SHOW server_version")).scalar_one()
        vector_version = connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname='vector'")
        ).scalar_one()
    admin.dispose()
    pytest_result = pytest_receipt(Path(os.environ["KORPUS_POSTGRES_JUNIT"]))
    backup_result = backup_receipt(
        Path(os.environ["KORPUS_BACKUP_PATH"]),
        Path(os.environ["KORPUS_BACKUP_ENCRYPTION_KEY_FILE"]),
        os.environ["KORPUS_BACKUP_KEY_ID"],
    )
    mutation_path = os.getenv("KORPUS_MUTATION_REPORT")
    mutation_result = (
        mutation_receipt(Path(mutation_path)) if mutation_path is not None else None
    )
    backup_duration = optional_duration("KORPUS_BACKUP_SECONDS")
    backup_result["duration_seconds"] = backup_duration
    restore_duration = optional_duration("KORPUS_RESTORE_SECONDS")
    verification_duration = optional_duration("KORPUS_VERIFY_SECONDS")
    recovery_timing_anchored = all(
        value is not None
        for value in (backup_duration, restore_duration, verification_duration)
    )
    total_recovery_duration = (
        backup_duration + restore_duration + verification_duration
        if recovery_timing_anchored
        and backup_duration is not None
        and restore_duration is not None
        and verification_duration is not None
        else None
    )
    same_state = source_digest == restored_digest and source_counts == restored_counts
    prerequisites_pass = all(
        (
            alembic_update_denied,
            all(value == "PASS" for value in ddl_denials.values()),
            pytest_result["live_postgres"] == "PASS",
            backup_result["manifest_verified"] is True,
            security_predicates_pass(
                dict(role),
                compartment_cases,
                policies,
                public_rows,
                public_restricted_rows,
            ),
        )
    )
    report = {
        "schema": "korpus.postgres-live-assurance.v1",
        "act_id": "KORPUS-ACT-01",
        "base_commit": os.environ["KORPUS_BASE_COMMIT"],
        "candidate_commit": candidate_commit(),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "postgres_image": "pgvector/pgvector:0.8.5-pg17-trixie",
            "measurement": "ANCHORED",
        },
        "postgres_server_version": server_version,
        "pgvector_version": vector_version,
        "alembic_expected_heads": list(heads),
        "source_database_revision": list(source_revision),
        "restored_database_revision": list(restored_revision),
        "application_role_properties": dict(role),
        "table_policy_inventory": policies,
        "grant_inventory": grants,
        "rls_cases": {
            "missing_context_counts": missing,
            "public_identity_public_rows": public_rows,
            "public_identity_restricted_rows": public_restricted_rows,
            "cross_corpus_direct_sql_restricted_rows": broadened,
        },
        "compartment_cases": compartment_cases,
        "ddl_denial_cases": {
            "alembic_update": "PASS" if alembic_update_denied else "FAIL",
            **ddl_denials,
        },
        "backup": backup_result,
        "restore": {
            "duration_seconds": restore_duration,
            "verification_seconds": verification_duration,
            "total_recovery_seconds": total_recovery_duration,
            "measurement": "ANCHORED" if recovery_timing_anchored else "UNAVAILABLE",
        },
        "source_state_digest": source_digest,
        "restored_state_digest": restored_digest,
        "pytest": pytest_result,
        "mutation": mutation_result or {"status": "UNAVAILABLE"},
        "iam_006_probe": {
            "status": "CONFIRMED_OPEN" if broadened else "NOT_REPRODUCED",
            "broadened_restricted_rows": broadened,
            "trust_anchor_independent_of_application": False,
        },
        "unexecuted_gates": [
            "independent post-change verification",
            "GitLab pipeline",
        ]
        + (
            []
            if mutation_result is not None
            else ["mutation shard for changed critical Python modules"]
        )
        + ([] if recovery_timing_anchored else ["anchored recovery timing"]),
        "production_authorized": False,
        "verdict": "PASS_WITH_CAVEATS"
        if prerequisites_pass
        and same_state
        and all(value == 0 for value in missing.values())
        else "FAIL",
    }
    output = ROOT / "var/act-01/postgres-live-assurance.json"
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(output)
    return 0 if report["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
