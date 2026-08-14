"""Database lock boundary for optimistic review transitions."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Connection

from korpus.domain.models import DocumentVersionRecord, ReviewState
from korpus.infrastructure.schema import versions

VersionMapper = Callable[[Any], DocumentVersionRecord]


class ReviewTransitionConflict(RuntimeError):
    """Optimistic state changed after the caller selected its expected review state."""


def load_current_for_update(
    connection: Connection,
    version_id: UUID,
    expected_state: ReviewState,
    version_mapper: VersionMapper,
) -> DocumentVersionRecord:
    """Own the parent row before any approval-derived evidence is sealed."""
    row = connection.execute(
        select(versions).where(versions.c.id == str(version_id)).with_for_update()
    ).mappings().first()
    if row is None:
        raise LookupError("version not found")
    current = version_mapper(row)
    if current.review_state is not expected_state:
        raise ReviewTransitionConflict("version state changed concurrently")
    return current
