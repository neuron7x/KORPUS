#!/usr/bin/env python3
"""Provision an issuer/DB shared key through the migration-owner identity."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text


def read_secret() -> bytes:
    path = os.getenv("KORPUS_DATABASE_CAPABILITY_KEY_FILE")
    if not path:
        raise SystemExit("KORPUS_DATABASE_CAPABILITY_KEY_FILE is required")
    value = Path(path).read_bytes().strip()
    if len(value) < 32:
        raise SystemExit("database capability key must contain at least 32 bytes")
    return value


database_url = os.environ["KORPUS_DATABASE_URL"]
key_id = os.environ["KORPUS_DATABASE_CAPABILITY_KEY_ID"]
if not key_id or len(key_id) > 128 or any(ord(char) < 33 or ord(char) > 126 for char in key_id):
    raise SystemExit("invalid database capability key id")
not_before = datetime.fromisoformat(
    os.environ["KORPUS_DATABASE_CAPABILITY_KEY_NOT_BEFORE"]
).astimezone(UTC)
expires_at = datetime.fromisoformat(
    os.environ["KORPUS_DATABASE_CAPABILITY_KEY_EXPIRES_AT"]
).astimezone(UTC)
if expires_at <= not_before:
    raise SystemExit("database capability key expiry must follow not-before")

engine = create_engine(database_url, pool_pre_ping=True)
with engine.begin() as connection:
    connection.execute(
        text(
            "INSERT INTO korpus_auth.capability_keys(key_id,secret,enabled,not_before,expires_at) "
            "VALUES (:key_id,:secret,true,:not_before,:expires_at) "
            "ON CONFLICT (key_id) DO UPDATE SET secret=excluded.secret,enabled=true,"
            "not_before=excluded.not_before,expires_at=excluded.expires_at"
        ),
        {
            "key_id": key_id,
            "secret": read_secret(),
            "not_before": not_before,
            "expires_at": expires_at,
        },
    )
engine.dispose()
print(f"provisioned PostgreSQL capability verification key: {key_id}")
