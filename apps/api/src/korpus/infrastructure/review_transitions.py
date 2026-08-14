from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from korpus.application.corpus_snapshot import version_evidence_digest
from korpus.domain.models import AccessTier, DocumentRecord, DocumentVersionRecord, Identity, ReviewState
from korpus.infrastructure.schema import documents, spans, versions

VersionMapper = Callable[[Any], DocumentVersionRecord]
DocumentMapper = Callable[[Any], DocumentRecord]
AuditAppender = Callable[[Connection, Identity, str, str, str | None, dict[str, Any]], tuple[int, str]]


class ReviewTransitionConflict(RuntimeError):
    """Optimistic state changed after the caller selected its expected review state."""


def _load_current(
    connection: Connection,
    version_id: UUID,
    expected_state: ReviewState,
    version_mapper: VersionMapper,
) -> DocumentVersionRecord:
    # Approval must own the parent version row before it seals derived evidence. On
    # PostgreSQL the evidence trigger takes a shared lock on this same row before any
    # span mutation, which serializes `seal -> approve` against insert/update/delete.
    # SQLite ignores FOR UPDATE but already serializes writers at the database level.
    row = connection.execute(
        select(versions).where(versions.c.id == str(version_id)).with_for_update()
    ).mappings().first()
    if row is None:
        raise LookupError("version not found")
    current = version_mapper(row)
    if current.review_state is not expected_state:
        raise ReviewTransitionConflict("version state changed concurrently")
    return current


def _reviewer_changes(
    current: DocumentVersionRecord,
    actor: Identity,
    target_state: ReviewState,
    *,
    acknowledge_near_duplicate: bool,
    acknowledge_extraction_quality: bool,
    reviewer_credential_id: str | None,
) -> dict[str, Any]:
    if target_state is ReviewState.METADATA_REVIEWED:
        if (
            current.near_duplicate_of_version_id is not None
            and not acknowledge_near_duplicate
        ):
            raise ValueError("near-duplicate finding must be explicitly acknowledged")
        if current.extraction_quality_flags and not acknowledge_extraction_quality:
            raise ValueError("extraction-quality findings must be explicitly acknowledged")
        changes: dict[str, Any] = {
            "metadata_reviewed_by": actor.subject,
            "metadata_reviewer_credential_id": reviewer_credential_id,
        }
        if current.near_duplicate_of_version_id is not None:
            changes["near_duplicate_acknowledged_by"] = actor.subject
        if current.extraction_quality_flags:
            changes["extraction_quality_acknowledged_by"] = actor.subject
        return changes
    if target_state is ReviewState.CONTENT_REVIEWED:
        return {
            "content_reviewed_by": actor.subject,
            "content_reviewer_credential_id": reviewer_credential_id,
        }
    return {}


def _retire_existing_approved(
    connection: Connection,
    current: DocumentVersionRecord,
    version_mapper: VersionMapper,
) -> None:
    existing_row = connection.execute(
        select(versions)
        .where(versions.c.document_id == str(current.document_id))
        .where(versions.c.review_state == ReviewState.APPROVED.value)
        .where(versions.c.is_current.is_(True))
        .where(versions.c.id != str(current.id))
    ).mappings().first()
    if existing_row is not None:
        existing = version_mapper(existing_row)
        if current.supersedes_version_id != existing.id:
            raise ValueError("approval must supersede the current approved version")
        connection.execute(
            update(versions)
            .where(versions.c.id == str(existing.id))
            .where(versions.c.is_current.is_(True))
            .values(is_current=False, state_version=existing.state_version + 1)
        )
        return
    if current.supersedes_version_id is None:
        return
    predecessor_row = connection.execute(
        select(versions).where(versions.c.id == str(current.supersedes_version_id))
    ).mappings().first()
    if predecessor_row is None or predecessor_row["review_state"] != ReviewState.APPROVED.value:
        raise ValueError("superseded version must be approved")


def _apply_access_tier(
    connection: Connection,
    current: DocumentVersionRecord,
    actor: Identity,
    access_tier: AccessTier | None,
    document_mapper: DocumentMapper,
) -> None:
    if access_tier is None:
        return
    document_row = connection.execute(
        select(documents).where(documents.c.id == str(current.document_id))
    ).mappings().one()
    document = document_mapper(document_row)
    if access_tier < document.classification.minimum_tier:
        raise ValueError("access_tier is below classification minimum")
    if int(access_tier) > int(actor.clearance):
        raise PermissionError("approver cannot assign a tier above own clearance")
    connection.execute(
        update(documents)
        .where(documents.c.id == str(current.document_id))
        .values(access_tier=int(access_tier))
    )


def _seal_evidence_digest(connection: Connection, version_id: UUID) -> str:
    """Seal the exact persisted evidence set before a version becomes retrievable."""
    # Lock every currently persisted span while computing the seal. The parent version
    # row is already FOR UPDATE-locked by `_load_current`; together with the PostgreSQL
    # trigger's parent FOR SHARE lock this also excludes concurrent insertion of a new
    # span until approval either commits or aborts.
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
        .with_for_update()
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


def _approval_changes(
    connection: Connection,
    current: DocumentVersionRecord,
    actor: Identity,
    *,
    reviewer_credential_id: str | None,
    access_tier: AccessTier | None,
    version_mapper: VersionMapper,
    document_mapper: DocumentMapper,
) -> dict[str, Any]:
    # Compute this from the rows that will become retrievable, in the same transaction
    # as approval. A stored text/hash mismatch or an empty evidence set aborts approval.
    evidence_digest = _seal_evidence_digest(connection, current.id)
    _retire_existing_approved(connection, current, version_mapper)
    _apply_access_tier(connection, current, actor, access_tier, document_mapper)
    return {
        "approved_at": datetime.now(UTC),
        "approved_by": actor.subject,
        "approver_credential_id": reviewer_credential_id,
        "evidence_digest": evidence_digest,
        "is_current": True,
    }


def _transition_changes(
    connection: Connection,
    current: DocumentVersionRecord,
    actor: Identity,
    target_state: ReviewState,
    *,
    acknowledge_near_duplicate: bool,
    acknowledge_extraction_quality: bool,
    reviewer_credential_id: str | None,
    access_tier: AccessTier | None,
    version_mapper: VersionMapper,
    document_mapper: DocumentMapper,
) -> dict[str, Any]:
    changes: dict[str, Any] = {
        "review_state": target_state.value,
        "state_version": current.state_version + 1,
    }
    changes.update(
        _reviewer_changes(
            current,
            actor,
            target_state,
            acknowledge_near_duplicate=acknowledge_near_duplicate,
            acknowledge_extraction_quality=acknowledge_extraction_quality,
            reviewer_credential_id=reviewer_credential_id,
        )
    )
    if target_state is ReviewState.APPROVED:
        changes.update(
            _approval_changes(
                connection,
                current,
                actor,
                reviewer_credential_id=reviewer_credential_id,
                access_tier=access_tier,
                version_mapper=version_mapper,
                document_mapper=document_mapper,
            )
        )
    elif target_state is ReviewState.REJECTED:
        changes["is_current"] = False
    return changes


def transition_version_in_connection(
    connection: Connection,
    *,
    actor: Identity,
    version_id: UUID,
    expected_state: ReviewState,
    target_state: ReviewState,
    note: str,
    acknowledge_near_duplicate: bool,
    acknowledge_extraction_quality: bool,
    reviewer_credential_id: str | None,
    access_tier: AccessTier | None,
    version_mapper: VersionMapper,
    document_mapper: DocumentMapper,
    append_audit: AuditAppender,
) -> tuple[DocumentVersionRecord, tuple[int, str]]:
    current = _load_current(connection, version_id, expected_state, version_mapper)
    changes = _transition_changes(
        connection,
        current,
        actor,
        target_state,
        acknowledge_near_duplicate=acknowledge_near_duplicate,
        acknowledge_extraction_quality=acknowledge_extraction_quality,
        reviewer_credential_id=reviewer_credential_id,
        access_tier=access_tier,
        version_mapper=version_mapper,
        document_mapper=document_mapper,
    )
    result = connection.execute(
        update(versions)
        .where(versions.c.id == str(version_id))
        .where(versions.c.review_state == expected_state.value)
        .where(versions.c.state_version == current.state_version)
        .values(**changes)
    )
    if result.rowcount != 1:
        raise ReviewTransitionConflict("optimistic review transition failed")
    updated = version_mapper(
        connection.execute(
            select(versions).where(versions.c.id == str(version_id))
        ).mappings().one()
    )
    anchor = append_audit(
        connection,
        actor,
        "document.review_transition",
        "document_version",
        str(version_id),
        {
            "from": expected_state.value,
            "to": target_state.value,
            "note": note,
            "state_version": updated.state_version,
            "approved_by": updated.approved_by,
            "reviewer_credential_id": reviewer_credential_id,
            "metadata_reviewer_credential_id": updated.metadata_reviewer_credential_id,
            "content_reviewer_credential_id": updated.content_reviewer_credential_id,
            "approver_credential_id": updated.approver_credential_id,
            "near_duplicate_acknowledged_by": updated.near_duplicate_acknowledged_by,
            "extraction_quality_flags": sorted(updated.extraction_quality_flags),
            "extraction_quality_acknowledged_by": updated.extraction_quality_acknowledged_by,
            "applied_access_tier": None if access_tier is None else int(access_tier),
            "evidence_digest": changes.get("evidence_digest"),
        },
    )
    return updated, anchor
