"""Deterministic retrieval-only context projection.

The projection may improve ranking, but the evidence text/hash are immutable and remain
the only material that may enter citations or claims.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from korpus.domain.models import DocumentRecord, DocumentVersionRecord, EvidenceSpanRecord

PROJECTION_SCHEMA_VERSION = 1
MAX_CONTEXT_FIELD = 300
MAX_ALIASES = 16


@dataclass(frozen=True, slots=True)
class ContextualProjection:
    schema_version: int
    retrieval_text: str
    evidence_text: str
    evidence_sha256: str
    projection_sha256: str


def _clean(value: str | None) -> str:
    return " ".join((value or "").strip().split())[:MAX_CONTEXT_FIELD]


def build_contextual_projection(
    span: EvidenceSpanRecord,
    document: DocumentRecord,
    version: DocumentVersionRecord,
    *,
    approved_aliases: Iterable[str] = (),
) -> ContextualProjection:
    evidence_hash = hashlib.sha256(span.text.encode("utf-8")).hexdigest()
    if evidence_hash != span.text_hash:
        raise ValueError("evidence hash mismatch before contextual projection")
    aliases = sorted({_clean(alias) for alias in approved_aliases if _clean(alias)})[:MAX_ALIASES]
    context_fields = [
        f"title={_clean(document.canonical_title)}",
        f"section={_clean(span.section)}",
        f"corpus={_clean(document.corpus_id)}",
        f"issuer={_clean(document.issuer)}",
        f"jurisdiction={_clean(document.jurisdiction)}",
        f"document_type={_clean(document.document_type)}",
        f"revision={_clean(version.revision)}",
        f"effective={version.in_force_from.isoformat() if version.in_force_from else ''}",
    ]
    if aliases:
        context_fields.append("aliases=" + " | ".join(aliases))
    context = " [KORPUS_CONTEXT] ".join(
        field for field in context_fields if not field.endswith("=")
    )
    retrieval_text = f"{context}\n{span.text}" if context else span.text
    projection_hash = hashlib.sha256(retrieval_text.encode("utf-8")).hexdigest()
    return ContextualProjection(
        schema_version=PROJECTION_SCHEMA_VERSION,
        retrieval_text=retrieval_text,
        evidence_text=span.text,
        evidence_sha256=evidence_hash,
        projection_sha256=projection_hash,
    )
