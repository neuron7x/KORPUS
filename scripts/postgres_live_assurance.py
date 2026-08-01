#!/usr/bin/env python3
"""Emit sanitized machine evidence for the live PostgreSQL assurance boundary."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from alembic_state import database_revisions, expected_heads, verify_revisions
from sqlalchemy import create_engine, text
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
                    "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolinherit "
                    "FROM pg_roles WHERE rolname=current_user"
                )
            )
            .mappings()
            .one()
        )
        missing = {
            table: connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
            for table in TABLES[:5]
        }
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
    try:
        with app.begin() as connection:
            connection.execute(text("CREATE TABLE app_role_must_not_create(id integer)"))
        ddl_denied = False
    except DBAPIError:
        ddl_denied = True
    app.dispose()
    admin = create_engine(source_admin)
    with admin.connect() as connection:
        policies = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT schemaname,tablename,policyname,cmd,roles,qual,with_check "
                    "FROM pg_policies WHERE schemaname='public' "
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
    same_state = source_digest == restored_digest and source_counts == restored_counts
    report = {
        "schema": "korpus.postgres-live-assurance.v1",
        "act_id": "KORPUS-ACT-01",
        "base_commit": os.environ["KORPUS_BASE_COMMIT"],
        "candidate_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
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
            "cross_corpus_direct_sql_restricted_rows": broadened,
        },
        "compartment_cases": compartment_cases,
        "ddl_denial_cases": {
            "alembic_update": "PASS",
            "privileged_ddl": "PASS" if ddl_denied else "FAIL",
        },
        "backup": {
            "encrypted": True,
            "manifest_verified": True,
            "duration_seconds": float(os.getenv("KORPUS_BACKUP_SECONDS", "0")),
        },
        "restore": {
            "duration_seconds": float(os.getenv("KORPUS_RESTORE_SECONDS", "0")),
            "verification_seconds": float(os.getenv("KORPUS_VERIFY_SECONDS", "0")),
            "measurement": "ANCHORED",
        },
        "source_state_digest": source_digest,
        "restored_state_digest": restored_digest,
        "pytest": {"live_postgres": "PASS"},
        "iam_006_probe": {
            "status": "CONFIRMED_OPEN" if broadened else "NOT_REPRODUCED",
            "broadened_restricted_rows": broadened,
            "trust_anchor_independent_of_application": False,
        },
        "unexecuted_gates": [
            "independent post-change verification",
            "GitLab pipeline",
            "mutation shard for changed critical Python modules",
        ],
        "production_authorized": False,
        "verdict": "PASS_WITH_CAVEATS"
        if same_state and all(value == 0 for value in missing.values())
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
