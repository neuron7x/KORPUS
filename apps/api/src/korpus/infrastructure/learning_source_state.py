"""Projection from canonical KORPUS evidence state into learning validation facts."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.engine import Connection

from korpus.domain.learning import BoundSourceState, CourseVersion
from korpus.infrastructure.schema import spans, versions


def load_bound_source_states(
    connection: Connection,
    version: CourseVersion,
) -> dict[str, BoundSourceState]:
    """Load only canonical facts needed to decide whether a course may serve."""

    requested = {
        binding.version_id
        for module in version.modules
        for lesson in module.lessons
        for binding in lesson.source_bindings
    }
    if not requested:
        return {}
    version_rows = (
        connection.execute(
            select(
                versions.c.id,
                versions.c.document_id,
                versions.c.review_state,
                versions.c.effective_from,
                versions.c.effective_until,
                versions.c.rescinded_at,
            ).where(versions.c.id.in_(sorted(requested)))
        )
        .mappings()
        .all()
    )
    span_rows = connection.execute(
        select(spans.c.version_id, spans.c.id).where(spans.c.version_id.in_(sorted(requested)))
    ).all()
    span_ids: dict[str, set[str]] = defaultdict(set)
    for version_id, span_id in span_rows:
        span_ids[str(version_id)].add(str(span_id))
    return {
        str(row["id"]): BoundSourceState(
            document_id=str(row["document_id"]),
            version_id=str(row["id"]),
            approved=str(row["review_state"]) == "approved",
            evidence_span_ids=frozenset(span_ids[str(row["id"])]),
            effective_from=row["effective_from"],
            effective_until=row["effective_until"],
            rescinded_at=row["rescinded_at"],
        )
        for row in version_rows
    }
