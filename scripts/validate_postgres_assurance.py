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
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
missing = sorted(set(REQUIRED) - payload.keys())
serialized = json.dumps(payload)
if (
    missing
    or payload.get("verdict") not in {"PASS", "PASS_WITH_CAVEATS", "FAIL"}
    or payload.get("production_authorized") is not False
    or re.search(r"postgres(?:ql)?://[^/\s]*:[^@\s]*@", serialized)
):
    raise SystemExit(f"invalid postgres assurance evidence; missing={missing}")
print("postgres assurance evidence schema valid")
