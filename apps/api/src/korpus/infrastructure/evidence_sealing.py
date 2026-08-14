"""Evidence sealing for the approval transaction boundary."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Connection

from korpus.application.corpus_snapshot import version_evidence_digest
from korpus.infrastructure.schema import spans


def seal_evidence_digest(connection: Connection, version_id: UUID) -> str:
    """Digest evidence while the caller owns the parent version lock.

    PostgreSQL evidence DML acquires a shared lock on that parent in a BEFORE trigger.
    Therefore a mutation either commits before this read or waits until approval commits
    and is rejected. Spans are intentionally not row-locked here: UPDATE/DELETE may lock
    the child tuple before their trigger asks for the parent, so parent->child locking in
    the approval path would introduce an avoidable lock inversion.
    """
    rows = connection.execute(
        select(
            spans.c.id,
            spans.c.ordinal,
            spans.c.page,
            spans.c.section,
            spans.c.text,
            spans.c.text_hash,
        )
        .where(spans.c.version_id == str(version_id))
        .order_by(spans.c.ordinal, spans.c.id)
    ).mappings().all()
    return version_evidence_digest(
        (
            str(row["id"]),
            int(row["ordinal"]),
            None if row["page"] is None else int(row["page"]),
            None if row["section"] is None else str(row["section"]),
            str(row["text"]),
            str(row["text_hash"]),
        )
        for row in rows
    )
