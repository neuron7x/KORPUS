#!/usr/bin/env python3
"""Verify a restored database through the non-superuser application role."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from alembic_state import database_revisions, verify_revisions
from korpus.domain.models import AccessTier, Identity
from korpus.security.database_capability import DatabaseCapabilityIssuer
from sqlalchemy import create_engine, text

url = os.environ["KORPUS_POSTGRES_TEST_URL"]
engine = create_engine(url, pool_pre_ping=True)
verify_revisions(database_revisions(url))
issuer = DatabaseCapabilityIssuer(
    os.environ["KORPUS_DATABASE_CAPABILITY_KEY_ID"],
    Path(os.environ["KORPUS_DATABASE_CAPABILITY_KEY_FILE"]).read_bytes().strip(),
)
now = datetime.now(UTC)
capability = issuer.issue(
    Identity(
        subject="restore-verifier",
        roles=frozenset({"admin", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public", "restricted-demo"}),
        compartments=frozenset({"omega"}),
    ),
    jti=f"restore-{uuid4()}",
    not_before=now - timedelta(seconds=5),
    expires_at=now + timedelta(seconds=60),
)
with engine.begin() as connection:
    # RLS must fail closed with no request identity.
    if connection.execute(text("SELECT count(*) FROM documents")).scalar_one() != 0:
        raise SystemExit("restored RLS leaked documents without identity")
    connection.execute(
        text("SELECT korpus_auth.activate(:capability)"), {"capability": capability}
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
