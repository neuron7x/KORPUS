"""Rows to records and back, with no database in sight.

The second and last piece of `SqlRepository` that separates cleanly (COD-001). These
functions map a result row onto a domain record, or a record onto column values. They
touch no connection, hold no transaction, and share nothing with the write path except
the shapes they produce — which is why moving them changes no ordering and no
visibility, and why the tests over the repository pass untouched.

Two families exist for one reason worth stating: `document`/`version` read the base
tables, `*_from_projection` read the retrieval projection, which names the same columns
differently because it joins. Collapsing them into one function with a flag would hide
that a projection row and a table row are different shapes, and the next person to add
a column would add it to whichever branch they happened to be reading.

What remains in the repository after this is the transactional core: writes that must
land with their audit event in one transaction. That part does not separate, and
pretending otherwise would spread one debt across more files.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    ReviewState,
)


def allowed_classifications(clearance: AccessTier) -> list[str]:
    allowed = [Classification.PUBLIC.value]
    if clearance >= AccessTier.AUTHENTICATED:
        allowed.append(Classification.INTERNAL.value)
    if clearance >= AccessTier.RESTRICTED:
        allowed.append(Classification.RESTRICTED.value)
    return allowed


def document(row: Any) -> DocumentRecord:
    return DocumentRecord(
        id=UUID(row["id"]),
        canonical_title=row["canonical_title"],
        corpus_id=row["corpus_id"],
        issuer=row["issuer"],
        jurisdiction=row["jurisdiction"],
        document_type=row["document_type"],
        access_tier=AccessTier(row["access_tier"]),
        classification=Classification(row["classification"]),
        compartments=frozenset(json.loads(row.get("compartments_json") or "[]")),
        created_at=row["created_at"],
    )


def document_from_projection(row: Any) -> DocumentRecord:
    return DocumentRecord(
        id=UUID(row["document_id"]),
        canonical_title=row["canonical_title"],
        corpus_id=row["corpus_id"],
        issuer=row["issuer"],
        jurisdiction=row["jurisdiction"],
        document_type=row["document_type"],
        access_tier=AccessTier(row["access_tier"]),
        classification=Classification(row["classification"]),
        compartments=frozenset(json.loads(row.get("compartments_json") or "[]")),
        created_at=row["document_created_at"],
    )


def document_values(record: DocumentRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "canonical_title": record.canonical_title,
        "corpus_id": record.corpus_id,
        "issuer": record.issuer,
        "jurisdiction": record.jurisdiction,
        "document_type": record.document_type,
        "access_tier": int(record.access_tier),
        "classification": record.classification.value,
        "compartments_json": json.dumps(sorted(record.compartments), separators=(",", ":")),
        "created_at": record.created_at,
    }


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def span_from_projection(row: Any) -> EvidenceSpanRecord:
    return EvidenceSpanRecord(
        id=UUID(row["span_id"]),
        version_id=UUID(row["span_version_id"]),
        ordinal=row["ordinal"],
        page=row["page"],
        section=row["section"],
        text=row["text"],
        text_hash=row["text_hash"],
        created_at=row["span_created_at"],
    )


def span_values(record: EvidenceSpanRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "version_id": str(record.version_id),
        "ordinal": record.ordinal,
        "page": record.page,
        "section": record.section,
        "text": record.text,
        "text_hash": record.text_hash,
        "created_at": record.created_at,
    }


def version(row: Any) -> DocumentVersionRecord:
    return DocumentVersionRecord(
        id=UUID(row["id"]),
        document_id=UUID(row["document_id"]),
        revision=row["revision"],
        publication_identifier=row["publication_identifier"],
        source_uri=row["source_uri"],
        source_hash=row["source_hash"],
        object_key=row["object_key"],
        mime_type=row["mime_type"],
        publication_date=row["publication_date"],
        effective_from=row["effective_from"],
        effective_until=row["effective_until"],
        rescinded_at=row["rescinded_at"],
        authority=AuthorityClass(row["authority"]),
        source_key_id=row.get("source_key_id"),
        source_signature_b64=row.get("source_signature_b64"),
        content_fingerprint=row.get("content_fingerprint") or "0" * 16,
        near_duplicate_of_version_id=(
            UUID(row["near_duplicate_of_version_id"])
            if row.get("near_duplicate_of_version_id")
            else None
        ),
        near_duplicate_similarity=row.get("near_duplicate_similarity"),
        near_duplicate_acknowledged_by=row.get("near_duplicate_acknowledged_by"),
        extraction_text_chars=int(row.get("extraction_text_chars") or 0),
        extraction_alnum_ratio=float(row.get("extraction_alnum_ratio") or 0.0),
        extraction_replacement_ratio=float(row.get("extraction_replacement_ratio") or 0.0),
        extraction_quality_flags=frozenset(
            json.loads(row.get("extraction_quality_flags_json") or "[]")
        ),
        extraction_quality_acknowledged_by=row.get("extraction_quality_acknowledged_by"),
        review_state=ReviewState(row["review_state"]),
        supersedes_version_id=(
            UUID(row["supersedes_version_id"]) if row["supersedes_version_id"] else None
        ),
        state_version=row["state_version"],
        metadata_reviewed_by=row["metadata_reviewed_by"],
        metadata_reviewer_credential_id=row.get("metadata_reviewer_credential_id"),
        content_reviewed_by=row["content_reviewed_by"],
        content_reviewer_credential_id=row.get("content_reviewer_credential_id"),
        approved_at=row["approved_at"],
        approved_by=row["approved_by"],
        approver_credential_id=row.get("approver_credential_id"),
        is_current=bool(row["is_current"]),
        created_at=row["created_at"],
    )


def version_from_projection(row: Any) -> DocumentVersionRecord:
    return DocumentVersionRecord(
        id=UUID(row["version_id"]),
        document_id=UUID(row["document_id"]),
        revision=row["revision"],
        publication_identifier=row["publication_identifier"],
        source_uri=row["source_uri"],
        source_hash=row["source_hash"],
        object_key=row["object_key"],
        mime_type=row["mime_type"],
        publication_date=row["publication_date"],
        effective_from=row["effective_from"],
        effective_until=row["effective_until"],
        rescinded_at=row["rescinded_at"],
        authority=AuthorityClass(row["authority"]),
        source_key_id=row.get("source_key_id"),
        source_signature_b64=row.get("source_signature_b64"),
        content_fingerprint=row.get("content_fingerprint") or "0" * 16,
        near_duplicate_of_version_id=(
            UUID(row["near_duplicate_of_version_id"])
            if row.get("near_duplicate_of_version_id")
            else None
        ),
        near_duplicate_similarity=row.get("near_duplicate_similarity"),
        near_duplicate_acknowledged_by=row.get("near_duplicate_acknowledged_by"),
        extraction_text_chars=int(row.get("extraction_text_chars") or 0),
        extraction_alnum_ratio=float(row.get("extraction_alnum_ratio") or 0.0),
        extraction_replacement_ratio=float(row.get("extraction_replacement_ratio") or 0.0),
        extraction_quality_flags=frozenset(
            json.loads(row.get("extraction_quality_flags_json") or "[]")
        ),
        extraction_quality_acknowledged_by=row.get("extraction_quality_acknowledged_by"),
        review_state=ReviewState(row["review_state"]),
        supersedes_version_id=(
            UUID(row["supersedes_version_id"]) if row["supersedes_version_id"] else None
        ),
        state_version=row["state_version"],
        metadata_reviewed_by=row["metadata_reviewed_by"],
        metadata_reviewer_credential_id=row.get("metadata_reviewer_credential_id"),
        content_reviewed_by=row["content_reviewed_by"],
        content_reviewer_credential_id=row.get("content_reviewer_credential_id"),
        approved_at=row["approved_at"],
        approved_by=row["approved_by"],
        approver_credential_id=row.get("approver_credential_id"),
        is_current=bool(row["is_current"]),
        created_at=row["version_created_at"],
    )


def version_values(record: DocumentVersionRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "document_id": str(record.document_id),
        "revision": record.revision,
        "publication_identifier": record.publication_identifier,
        "source_uri": record.source_uri,
        "source_hash": record.source_hash,
        "object_key": record.object_key,
        "mime_type": record.mime_type,
        "publication_date": record.publication_date,
        "effective_from": record.effective_from,
        "effective_until": record.effective_until,
        "rescinded_at": record.rescinded_at,
        "authority": record.authority.value,
        "source_key_id": record.source_key_id,
        "source_signature_b64": record.source_signature_b64,
        "content_fingerprint": record.content_fingerprint,
        "near_duplicate_of_version_id": (
            str(record.near_duplicate_of_version_id)
            if record.near_duplicate_of_version_id
            else None
        ),
        "near_duplicate_similarity": record.near_duplicate_similarity,
        "near_duplicate_acknowledged_by": record.near_duplicate_acknowledged_by,
        "extraction_text_chars": record.extraction_text_chars,
        "extraction_alnum_ratio": record.extraction_alnum_ratio,
        "extraction_replacement_ratio": record.extraction_replacement_ratio,
        "extraction_quality_flags_json": json.dumps(
            sorted(record.extraction_quality_flags), separators=(",", ":")
        ),
        "extraction_quality_acknowledged_by": record.extraction_quality_acknowledged_by,
        "review_state": record.review_state.value,
        "supersedes_version_id": (
            str(record.supersedes_version_id) if record.supersedes_version_id else None
        ),
        "state_version": record.state_version,
        "metadata_reviewed_by": record.metadata_reviewed_by,
        "metadata_reviewer_credential_id": record.metadata_reviewer_credential_id,
        "content_reviewed_by": record.content_reviewed_by,
        "content_reviewer_credential_id": record.content_reviewer_credential_id,
        "approved_at": record.approved_at,
        "approved_by": record.approved_by,
        "approver_credential_id": record.approver_credential_id,
        "is_current": record.is_current,
        "created_at": record.created_at,
    }
