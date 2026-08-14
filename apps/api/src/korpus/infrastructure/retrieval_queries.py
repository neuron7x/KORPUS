"""Building the retrieval projection, apart from executing it.

COD-001, second seam: "search" is one of the six responsibilities the finding names
inside `SqlRepository`. Every function here constructs a statement and none of them
opens a transaction — which is the line worth drawing, because these are exactly the
predicates that decide what a reader may see. Clearance, classification, compartment,
currency and supersession all live in this file, and a test can now reason about the
statement without a database under it.

Execution, the RLS session context and the retry envelope stay in the repository: they
are the transactional half, and moving them here would recreate the coupling the split
is meant to remove.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.engine import RowMapping

from korpus.domain.models import (
    AuthorityClass,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    ReviewState,
)
from korpus.infrastructure import row_mapping
from korpus.infrastructure.schema import document_compartments, documents, spans, versions


def compartment_predicate(identity: Identity) -> Any:
    unauthorized = (
        select(1)
        .select_from(document_compartments)
        .where(document_compartments.c.document_id == documents.c.id)
    )
    if identity.compartments:
        unauthorized = unauthorized.where(
            document_compartments.c.compartment.not_in(sorted(identity.compartments))
        )
    return ~unauthorized.exists()


def _visibility_filters(
    identity: Identity, authorized_corpora: frozenset[str], as_of: date
) -> list[Any]:
    """Which versions this reader may retrieve at all, as clauses both projections share."""
    allowed_classifications = row_mapping.allowed_classifications(identity.clearance)
    superseding = versions.alias("superseding_version")
    active_superseder = (
        select(1)
        .where(superseding.c.supersedes_version_id == versions.c.id)
        .where(superseding.c.document_id == versions.c.document_id)
        .where(superseding.c.review_state == ReviewState.APPROVED.value)
        .where(
            func.coalesce(superseding.c.effective_from, superseding.c.publication_date)
            <= as_of
        )
        .where(
            (superseding.c.effective_until.is_(None))
            | (superseding.c.effective_until >= as_of)
        )
        .where(
            (superseding.c.rescinded_at.is_(None))
            | (func.date(superseding.c.rescinded_at) > as_of)
        )
        .exists()
    )
    return [
        versions.c.review_state == ReviewState.APPROVED.value,
        documents.c.corpus_id.in_(sorted(authorized_corpora)),
        documents.c.access_tier <= int(identity.clearance),
        documents.c.classification.in_(allowed_classifications),
        compartment_predicate(identity),
        ~active_superseder,
    ]


def release_projection(
    identity: Identity, authorized_corpora: frozenset[str], as_of: date
) -> Any:
    """The versions behind the retrievable spans, once each, without the spans."""
    return (
        select(
            documents.c.id.label("document_id"),
            versions.c.id.label("version_id"),
            versions.c.source_hash,
            versions.c.review_state,
            versions.c.publication_date,
            versions.c.effective_from,
            versions.c.effective_until,
            versions.c.rescinded_at,
        )
        .select_from(spans)
        .join(versions, spans.c.version_id == versions.c.id)
        .join(documents, versions.c.document_id == documents.c.id)
        .where(*_visibility_filters(identity, authorized_corpora, as_of))
        .distinct()
        .order_by(documents.c.id, versions.c.id)
    )


def retrievable_projection(
    identity: Identity, authorized_corpora: frozenset[str], as_of: date
) -> Any:
    return (
        select(
            spans.c.id.label("span_id"),
            spans.c.version_id.label("span_version_id"),
            spans.c.ordinal,
            spans.c.page,
            spans.c.section,
            spans.c.text,
            spans.c.text_hash,
            spans.c.created_at.label("span_created_at"),
            documents.c.id.label("document_id"),
            documents.c.canonical_title,
            documents.c.corpus_id,
            documents.c.issuer,
            documents.c.jurisdiction,
            documents.c.document_type,
            documents.c.access_tier,
            documents.c.classification,
            documents.c.compartments_json,
            documents.c.created_at.label("document_created_at"),
            versions.c.id.label("version_id"),
            versions.c.revision,
            versions.c.publication_identifier,
            versions.c.source_uri,
            versions.c.source_hash,
            versions.c.object_key,
            versions.c.mime_type,
            versions.c.publication_date,
            versions.c.effective_from,
            versions.c.effective_until,
            versions.c.rescinded_at,
            versions.c.authority,
            versions.c.source_key_id,
            versions.c.source_signature_b64,
            versions.c.content_fingerprint,
            versions.c.near_duplicate_of_version_id,
            versions.c.near_duplicate_similarity,
            versions.c.near_duplicate_acknowledged_by,
            versions.c.extraction_text_chars,
            versions.c.extraction_alnum_ratio,
            versions.c.extraction_replacement_ratio,
            versions.c.extraction_quality_flags_json,
            versions.c.extraction_quality_acknowledged_by,
            versions.c.review_state,
            versions.c.supersedes_version_id,
            versions.c.state_version,
            versions.c.metadata_reviewed_by,
            versions.c.metadata_reviewer_credential_id,
            versions.c.content_reviewed_by,
            versions.c.content_reviewer_credential_id,
            versions.c.approved_at,
            versions.c.approved_by,
            versions.c.approver_credential_id,
            versions.c.is_current,
            versions.c.created_at.label("version_created_at"),
        )
        .join(versions, spans.c.version_id == versions.c.id)
        .join(documents, versions.c.document_id == documents.c.id)
        .where(*_visibility_filters(identity, authorized_corpora, as_of))
        .order_by(documents.c.id, versions.c.created_at.desc(), spans.c.ordinal)
    )


def materialize_current(
    rows: Sequence[RowMapping], as_of: date
) -> list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]]:
    authorized: list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]] = []
    for row in rows:
        version = row_mapping.version_from_projection(row)
        if not version.is_valid_on(as_of):
            continue
        authorized.append(
            (
                row_mapping.span_from_projection(row),
                row_mapping.document_from_projection(row),
                version,
            )
        )
    return authorized


def release_row_is_current(row: Any, as_of: date) -> bool:
    """`DocumentVersionRecord.is_valid_on`, asked of a row that carries only dates."""
    probe = DocumentVersionRecord(
        id=UUID(str(row["version_id"])),
        document_id=UUID(str(row["document_id"])),
        revision="",
        source_hash=str(row["source_hash"]),
        object_key="",
        mime_type="application/octet-stream",
        publication_date=row["publication_date"],
        effective_from=row["effective_from"],
        effective_until=row["effective_until"],
        rescinded_at=row["rescinded_at"],
        authority=AuthorityClass.UNKNOWN,
        review_state=ReviewState(str(row["review_state"])),
    )
    return probe.is_valid_on(as_of)


def _candidate_compartment_filter(identity: Identity) -> tuple[str, dict[str, str]]:
    compartments = sorted(identity.compartments)
    parameters = {f"compartment_{index}": value for index, value in enumerate(compartments)}
    forbidden = ""
    if compartments:
        placeholders = ",".join(parameters)
        forbidden = f"AND dc.compartment NOT IN ({placeholders})"
    clause = (
        "AND NOT EXISTS (SELECT 1 FROM document_compartments dc "
        f"WHERE dc.document_id = d.id {forbidden})"
    )
    return clause, parameters


def candidate_span_query(
    identity: Identity,
    corpora: frozenset[str],
    as_of: date,
    query: str,
    limit: int,
    dialect: str,
) -> tuple[Any, dict[str, Any]] | None:
    """The bounded full-text candidate statement, before canonical materialization."""
    from korpus.application.retrieval import candidate_terms

    term_specs = candidate_terms(query)
    terms = [value for value, _ in term_specs]
    if not terms:
        return None
    classifications = row_mapping.allowed_classifications(identity.clearance)
    corpus_placeholders = ",".join(
        f":corpus_{index}" for index, _ in enumerate(sorted(corpora))
    )
    class_placeholders = ",".join(
        f":class_{index}" for index, _ in enumerate(classifications)
    )
    compartment_clause, compartment_parameters = _candidate_compartment_filter(identity)
    parameters: dict[str, Any] = {
        "clearance": int(identity.clearance),
        "as_of": as_of.isoformat(),
        "limit": limit,
    }
    parameters.update({f"corpus_{index}": value for index, value in enumerate(sorted(corpora))})
    parameters.update(
        {f"class_{index}": value for index, value in enumerate(classifications)}
    )
    parameters.update(compartment_parameters)
    if dialect == "sqlite":
        match_query = " OR ".join(
            f'"{term.replace(chr(34), chr(34) * 2)}"' + ("*" if prefix else "")
            for term, prefix in term_specs
        )
        parameters["query"] = match_query
        statement = sql_text(
            f"""
            WITH superseded AS (
              SELECT DISTINCT sv.supersedes_version_id AS id, sv.document_id AS document_id
              FROM document_versions sv
              WHERE sv.supersedes_version_id IS NOT NULL
                AND sv.review_state = 'approved'
                AND COALESCE(sv.effective_from, sv.publication_date) <= :as_of
                AND (sv.effective_until IS NULL OR sv.effective_until >= :as_of)
                AND (sv.rescinded_at IS NULL OR date(sv.rescinded_at) > :as_of)
            )
            SELECT s.id AS span_id
            FROM evidence_fts f
            JOIN evidence_spans s ON s.id = f.span_id
            JOIN document_versions v ON v.id = s.version_id
            JOIN documents d ON d.id = v.document_id
            WHERE evidence_fts MATCH :query
              AND v.review_state = 'approved'
              AND d.corpus_id IN ({corpus_placeholders})
              AND d.access_tier <= :clearance
              AND d.classification IN ({class_placeholders})
              {compartment_clause}
              AND COALESCE(v.effective_from, v.publication_date) <= :as_of
              AND (v.effective_until IS NULL OR v.effective_until >= :as_of)
              AND (v.rescinded_at IS NULL OR date(v.rescinded_at) > :as_of)
              AND (v.id, v.document_id) NOT IN (SELECT id, document_id FROM superseded)
            ORDER BY bm25(evidence_fts), s.id
            LIMIT :limit
            """
        )
    elif dialect == "postgresql":
        parameters["query"] = " | ".join(
            f"{term}:*" if prefix else term for term, prefix in term_specs
        )
        as_of_date = "CAST(:as_of AS date)"
        statement = sql_text(
            f"""
            WITH superseded AS (
              SELECT DISTINCT sv.supersedes_version_id AS id, sv.document_id AS document_id
              FROM document_versions sv
              WHERE sv.supersedes_version_id IS NOT NULL
                AND sv.review_state = 'approved'
                AND COALESCE(sv.effective_from, sv.publication_date) <= {as_of_date}
                AND (sv.effective_until IS NULL OR sv.effective_until >= {as_of_date})
                AND (sv.rescinded_at IS NULL OR CAST(sv.rescinded_at AS date) > {as_of_date})
            )
            SELECT s.id AS span_id
            FROM evidence_spans s
            JOIN document_versions v ON v.id = s.version_id
            JOIN documents d ON d.id = v.document_id
            WHERE to_tsvector('simple', s.text) @@ to_tsquery('simple', :query)
              AND v.review_state = 'approved'
              AND d.corpus_id IN ({corpus_placeholders})
              AND d.access_tier <= :clearance
              AND d.classification IN ({class_placeholders})
              {compartment_clause}
              AND COALESCE(v.effective_from, v.publication_date) <= {as_of_date}
              AND (v.effective_until IS NULL OR v.effective_until >= {as_of_date})
              AND (v.rescinded_at IS NULL OR CAST(v.rescinded_at AS date) > {as_of_date})
              AND (v.id, v.document_id) NOT IN (SELECT id, document_id FROM superseded)
            ORDER BY ts_rank_cd(
                to_tsvector('simple', s.text), to_tsquery('simple', :query)
            ) DESC, s.id
            LIMIT :limit
            """
        )
    else:
        raise RuntimeError(f"unsupported search dialect: {dialect}")
    return statement, parameters
