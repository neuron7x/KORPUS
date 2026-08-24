"""Reader-facing exact source passage schema.

The API route only authorizes and selects.  This module owns the stable disclosure
projection so adding validity/provenance fields cannot bloat the routing surface.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from korpus.domain.models import (
    AuthorityClass,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
)


class DisclosedSpan(BaseModel):
    """One exact passage plus the source-version facts needed to verify its currency."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    version_id: UUID
    document_id: UUID
    document_title: str
    revision: str
    ordinal: int
    page: int | None
    section: str | None
    text: str
    text_hash: str
    source_hash: str
    source_uri: str | None
    authority: AuthorityClass
    publication_date: date | None
    effective_from: date | None
    effective_until: date | None
    rescinded_at: datetime | None

    @classmethod
    def build(
        cls,
        span: EvidenceSpanRecord,
        document: DocumentRecord,
        version: DocumentVersionRecord,
    ) -> DisclosedSpan:
        return cls(
            id=span.id,
            version_id=version.id,
            document_id=document.id,
            document_title=document.canonical_title,
            revision=version.revision,
            ordinal=span.ordinal,
            page=span.page,
            section=span.section,
            text=span.text,
            text_hash=span.text_hash,
            source_hash=version.source_hash,
            source_uri=version.source_uri,
            authority=version.authority,
            publication_date=version.publication_date,
            effective_from=version.effective_from,
            effective_until=version.effective_until,
            rescinded_at=version.rescinded_at,
        )
