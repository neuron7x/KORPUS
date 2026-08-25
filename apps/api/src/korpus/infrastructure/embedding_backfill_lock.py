"""Session-scoped PostgreSQL singleton lease for embedding reconciliation."""

from __future__ import annotations

import hashlib
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy import text as sql_text


def _lock_key(model_id: str, dimensions: int) -> int:
    digest = hashlib.sha256(f"korpus:embedding:{model_id}:{dimensions}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


@contextmanager
def exclusive_backfill_run(
    engine: Engine, model_id: str, dimensions: int
) -> Generator[None, None, None]:
    """Refuse concurrent runs; hold the session lock across every committed batch."""
    connection = engine.connect()
    key = _lock_key(model_id, dimensions)
    acquired = False
    try:
        acquired = bool(
            connection.execute(
                sql_text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            ).scalar_one()
        )
        if not acquired:
            raise RuntimeError("embedding reconciliation is already running")
        yield
    finally:
        if acquired:
            connection.execute(sql_text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        connection.close()
