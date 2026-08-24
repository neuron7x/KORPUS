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

from sqlalchemy import func, select
from sqlalchemy.engine import RowMapping

from korpus.domain.models import (
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    ReviewState,
    version_is_valid_on_fields,
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
    """Which versions this reader may retrieve at all, as clauses both projections share.

    Written once because a second copy is how the two drift: the release identity below
    is meant to be the fingerprint of exactly the material an answer could have been
    drawn from, and a projection that filters slightly differently would produce a
    release id for a corpus nobody can read.
    """
    allowed_classifications = row_mapping.allowed_classifications(identity.clearance)
    superseding = versions.alias("superseding_version")
    active_superseder = (
        select(1)
        .where(superseding.c.supersedes_version_id == versions.c.id)
        # Second line of the same rule the ingest path states: a successor belongs
        # to the same canonical document. The application refuses to write a
        # crossing edge; this refuses to honour one, because a row already in the
        # database, an import from another tool, or a future path that forgets the
        # check would otherwise let any document remove any other from retrieval.
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
    """The versions behind the retrievable spans, once each, without the spans.

    `corpus_release_id` used to read the full span projection and build a span, a
    document and a version model for every row. On 116 229 spans that was 232 458
    Pydantic constructions per question — measured 2026-08-06 as 17 s of a 23 s answer,
    while the retrieval it guards has a 1200 ms budget. The digest only ever used four
    strings per *version*, and there are 1616 of those.

    Joined through `evidence_spans` deliberately: a version with no retrievable span
    contributes nothing to any answer, and the set this identifies is the set an answer
    could be drawn from.
    """
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
        # Stated because no span column is selected: without it SQLAlchemy cannot tell
        # which of the three tables the join starts from.
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
    rows: Sequence[RowMapping],
    as_of: date,
    *,
    limit: int | None = None,
) -> list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]]:
    """Materialize current rows, optionally stopping after enough valid results.

    SQL already applies the currency predicate, but the domain check is retained as a
    fail-closed second line. Candidate search can therefore stop constructing Pydantic
    objects once the requested number of *valid* rows has been reached without changing
    ordering or the returned set.
    """
    if limit is not None and limit < 1:
        return []
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
        if limit is not None and len(authorized) >= limit:
            break
    return authorized


def release_row_is_current(row: Any, as_of: date) -> bool:
    """Projection-only call into the same currency predicate as the domain record.

    `corpus_release_id` can inspect thousands of versions per question. Constructing a
    full Pydantic `DocumentVersionRecord` only to read four date fields is semantically
    redundant and measurably expensive; this remains single-source-of-truth because the
    model method delegates to the same pure predicate.
    """
    return version_is_valid_on_fields(
        as_of,
        publication_date=row["publication_date"],
        effective_from=row["effective_from"],
        effective_until=row["effective_until"],
        rescinded_at=row["rescinded_at"],
    )


from korpus.infrastructure.retrieval_candidate_query import candidate_span_query
