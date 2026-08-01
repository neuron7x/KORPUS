#!/usr/bin/env python3
"""Run the live IAM-006 capability boundary and emit sanitized evidence."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from alembic_state import database_revisions, expected_heads
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "var/act-25/database-capability-assurance.json"
JUNIT = ROOT / "var/act-25/database-capability-junit.xml"
COMMIT = re.compile(r"[0-9a-f]{40}")


def commit() -> str:
    value = os.getenv("KORPUS_CANDIDATE_COMMIT")
    if value is None:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    if not COMMIT.fullmatch(value):
        raise ValueError("candidate commit must be a full lowercase Git SHA-1")
    return value


def main() -> int:
    started = datetime.now(UTC)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.unlink(missing_ok=True)
    JUNIT.unlink(missing_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "apps/api/tests/test_postgres_capability_integration.py",
            "-m",
            "postgres",
            f"--junitxml={JUNIT}",
        ],
        cwd=ROOT,
        check=False,
    )
    app = create_engine(os.environ["KORPUS_POSTGRES_TEST_URL"], pool_pre_ping=True)
    with app.connect() as connection:
        role = dict(
            connection.execute(
                text(
                    "SELECT current_user,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,"
                    "rolinherit FROM pg_roles WHERE rolname=current_user"
                )
            ).mappings().one()
        )
        private_access = {
            table: connection.execute(
                text("SELECT has_table_privilege(current_user,:table,'SELECT')"),
                {"table": f"korpus_auth.{table}"},
            ).scalar_one()
            for table in ("capability_keys", "consumed_capabilities")
        }
    app.dispose()
    heads = list(expected_heads())
    revisions = list(database_revisions(os.environ["KORPUS_POSTGRES_ADMIN_URL"]))
    predicates = {
        "legacy_guc_broadening_denied": result.returncode == 0,
        "tamper_denied": result.returncode == 0,
        "transaction_replay_denied": result.returncode == 0,
        "missing_context_denied": result.returncode == 0,
        "cross_corpus_denied": result.returncode == 0,
        "compartment_scope_enforced": result.returncode == 0,
        "read_only_write_denied": result.returncode == 0,
        "authorized_scoped_write_allowed": result.returncode == 0,
        "private_key_tables_denied": all(value is False for value in private_access.values()),
        "schema_at_authoritative_head": revisions == heads and len(heads) == 1,
    }
    local_pass = all(predicates.values()) and all(
        role[name] is False
        for name in ("rolsuper", "rolbypassrls", "rolcreatedb", "rolcreaterole", "rolinherit")
    )
    report = {
        "schema": "korpus.database-capability-assurance.v1",
        "act_id": "KORPUS-ACT-25",
        "candidate_commit": commit(),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "postgres_image": "pgvector/pgvector:0.8.5-pg17-trixie",
            "measurement": "ANCHORED_LOCAL",
        },
        "alembic_expected_heads": heads,
        "database_revisions": revisions,
        "application_role": role,
        "private_table_access": private_access,
        "predicates": predicates,
        "pytest": {
            "exit_code": result.returncode,
            "junit": JUNIT.name,
            "status": "PASS" if result.returncode == 0 else "FAIL",
        },
        "issuer_boundary": {
            "protocol_exercised": result.returncode == 0,
            "independent_broker_deployed": False,
            "reference_gate_process_has_signing_key": True,
            "api_runtime_accepts_signing_key": False,
            "status": "UNEXECUTED_EXTERNAL_DEPLOYMENT",
        },
        "unexecuted_gates": [
            "independent broker deployment and compromise test",
            "independent post-change verification",
            "GitLab pipeline",
        ],
        "production_authorized": False,
        "verdict": "PASS_WITH_CAVEATS" if local_pass else "FAIL",
    }
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT)
    print(OUTPUT)
    return 0 if local_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
