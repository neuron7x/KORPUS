#!/usr/bin/env python3
"""Verify a restored database through the non-superuser application role."""
from __future__ import annotations

import ast
import os
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "apps/api/migrations/versions"


def migration_head() -> str:
    """The revision no other migration names as its down_revision.

    This was the literal "0003_infrastructure_hardening" until 2026-08-03 — four
    revisions behind head, so the check could not pass once 0004 existed. It had
    never been contradicted because the job it runs in died at migration 0001.
    Deriving it from the files means the expectation moves with the schema.
    """
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in sorted(VERSIONS.glob("*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            target = None
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target = node.target.id
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                first = node.targets[0]
                target = first.id if isinstance(first, ast.Name) else None
            value = getattr(node, "value", None)
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                continue
            if target == "revision":
                revisions.add(value.value)
            elif target == "down_revision":
                parents.add(value.value)
    heads = sorted(revisions - parents)
    if len(heads) != 1:
        raise SystemExit(f"expected exactly one migration head, found {heads}")
    return heads[0]


url = os.environ["KORPUS_POSTGRES_TEST_URL"]
expected_revision = migration_head()
engine = create_engine(url, pool_pre_ping=True)
with engine.begin() as connection:
    revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    if revision != expected_revision:
        raise SystemExit(
            f"restored database is at migration {revision!r}, expected {expected_revision!r}"
        )
    # RLS must fail closed with no request identity.
    if connection.execute(text("SELECT count(*) FROM documents")).scalar_one() != 0:
        raise SystemExit("restored RLS leaked documents without identity")
    connection.execute(text("SELECT set_config('korpus.subject', 'restore-verifier', true)"))
    connection.execute(text("SELECT set_config('korpus.roles', 'admin,user', true)"))
    connection.execute(text("SELECT set_config('korpus.clearance', '3', true)"))
    connection.execute(text("SELECT set_config('korpus.corpora', 'public,restricted-demo', true)"))
    connection.execute(
        text("SELECT set_config('korpus.classifications', 'public,internal,restricted', true)")
    )
    if connection.execute(text("SELECT count(*) FROM documents")).scalar_one() < 2:
        raise SystemExit("restored corpus rows are missing")
    audit_head_query = text("SELECT count(*) FROM audit_heads WHERE singleton_id=1")
    if connection.execute(audit_head_query).scalar_one() != 1:
        raise SystemExit("restored audit head is missing")
engine.dispose()
print("restored PostgreSQL database passed schema, RLS, corpus, and audit-head checks")
