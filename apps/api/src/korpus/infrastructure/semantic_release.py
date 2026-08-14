"""Canonical semantic projection used by temporal release identity v2."""
from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from korpus.application.corpus_snapshot import (
    CorpusConsistencyError,
    SemanticReleaseMember,
    canonical_optional,
    canonical_set,
)
from korpus.infrastructure.schema import document_compartments, documents, versions


def _optional_temporal(value: date | datetime | None) -> str:
    if value is None:
        return canonical_optional(None)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        rendered = value.astimezone(UTC).isoformat()
    else:
        rendered = value.isoformat()
    return canonical_optional(rendered)


def _stored_compartments(value: object) -> str:
    try:
        decoded = json.loads(str(value or "[]"))
    except (TypeError, ValueError) as exc:
        raise CorpusConsistencyError("document compartments_json is not valid JSON") from exc
    if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
        raise CorpusConsistencyError("document compartments_json is not a string list")
    return canonical_set(decoded)


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def semantic_release_members(
    connection: Connection,
    visible_rows: Sequence[Any],
) -> list[SemanticReleaseMember]:
    """Read every answer-visible/decision-relevant field for the visible version set."""
    visible_pairs = {
        (str(row["document_id"]), str(row["version_id"])) for row in visible_rows
    }
    if not visible_pairs:
        return []
    version_ids = sorted(version_id for _document_id, version_id in visible_pairs)
    document_ids = sorted({document_id for document_id, _version_id in visible_pairs})
    statement = (
        select(
            documents.c.id.label("document_id"),
            documents.c.canonical_title,
            documents.c.corpus_id,
            documents.c.access_tier,
            documents.c.classification,
            documents.c.compartments_json,
            versions.c.id.label("version_id"),
            versions.c.source_hash,
            versions.c.review_state,
            versions.c.evidence_digest,
            versions.c.revision,
            versions.c.source_uri,
            versions.c.publication_date,
            versions.c.effective_from,
            versions.c.effective_until,
            versions.c.rescinded_at,
            versions.c.authority,
            versions.c.supersedes_version_id,
        )
        .select_from(versions)
        .join(documents, versions.c.document_id == documents.c.id)
        .where(versions.c.id.in_(version_ids))
        .order_by(documents.c.id, versions.c.id)
    )
    rows = connection.execute(statement).mappings().all()
    found_pairs = {(str(row["document_id"]), str(row["version_id"])) for row in rows}
    if found_pairs != visible_pairs:
        raise CorpusConsistencyError("release semantic projection is incomplete or mismatched")

    compartment_rows = connection.execute(
        select(document_compartments.c.document_id, document_compartments.c.compartment)
        .where(document_compartments.c.document_id.in_(document_ids))
        .order_by(document_compartments.c.document_id, document_compartments.c.compartment)
    ).all()
    visibility: dict[str, list[str]] = {document_id: [] for document_id in document_ids}
    for document_id, compartment in compartment_rows:
        visibility[str(document_id)].append(str(compartment))

    members: list[SemanticReleaseMember] = []
    for row in rows:
        evidence_digest = row["evidence_digest"]
        if not _valid_sha256(evidence_digest):
            raise CorpusConsistencyError("approved release member has no valid evidence digest")
        document_id = str(row["document_id"])
        members.append(
            SemanticReleaseMember(
                document_id=document_id,
                version_id=str(row["version_id"]),
                source_hash=str(row["source_hash"]),
                review_state=str(row["review_state"]),
                evidence_digest=evidence_digest,
                canonical_title=str(row["canonical_title"]),
                corpus_id=str(row["corpus_id"]),
                access_tier=str(int(row["access_tier"])),
                classification=str(row["classification"]),
                document_compartments=_stored_compartments(row["compartments_json"]),
                visibility_compartments=canonical_set(visibility[document_id]),
                revision=str(row["revision"]),
                source_uri=canonical_optional(row["source_uri"]),
                publication_date=_optional_temporal(row["publication_date"]),
                effective_from=_optional_temporal(row["effective_from"]),
                effective_until=_optional_temporal(row["effective_until"]),
                rescinded_at=_optional_temporal(row["rescinded_at"]),
                authority=str(row["authority"]),
                supersedes_version_id=canonical_optional(row["supersedes_version_id"]),
            )
        )
    return members
