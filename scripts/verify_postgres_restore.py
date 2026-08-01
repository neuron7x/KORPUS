#!/usr/bin/env python3
"""Verify a restored database through the non-superuser application role."""

from __future__ import annotations

import os

from alembic_state import database_revisions, verify_revisions
from sqlalchemy import create_engine, text

url = os.environ["KORPUS_POSTGRES_TEST_URL"]
engine = create_engine(url, pool_pre_ping=True)
verify_revisions(database_revisions(url))
with engine.begin() as connection:
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
    if (
        connection.execute(
            text("SELECT count(*) FROM audit_heads WHERE singleton_id=1")
        ).scalar_one()
        != 1
    ):
        raise SystemExit("restored audit head is missing")
engine.dispose()
print("restored PostgreSQL database passed schema, RLS, corpus, and audit-head checks")
