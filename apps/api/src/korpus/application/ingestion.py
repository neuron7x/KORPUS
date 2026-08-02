"""Document intake.

Ingestion decides three things that the answer path can no longer question: what a
chunk is, who says it, and whether anyone has reviewed it. All three are recorded
with the content, so a citation can be traced back to a file and a hash rather than
to a filename that may since have been replaced.

Identity is derived from content, not from position: the same file ingested twice
produces the same chunk ids and the store rejects the duplicate. That is what makes
re-running an import safe on a bad connection, which is the normal case here.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid5

from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Citation,
    EvidenceSpan,
    ReviewState,
)

# Fixed namespace: chunk ids must be reproducible across machines and runs.
NAMESPACE = UUID("1b5e9a2c-0f4a-4c8f-9a1e-5f0d3c7b6a20")
PARAGRAPH = re.compile(r"\n\s*\n")
MAX_QUOTE = 1200


@dataclass(frozen=True)
class SourceDescriptor:
    """Everything a reviewer must state before a document may be cited."""

    corpus_id: UUID
    title: str
    authority: AuthorityClass
    access_tier: AccessTier = AccessTier.PUBLIC
    review_state: ReviewState = ReviewState.QUARANTINED
    revision: str | None = None
    source_uri: str | None = None
    valid_until: datetime | None = None


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_paragraphs(text: str) -> list[str]:
    """Paragraph chunking.

    Deliberately not token-window chunking: a citation must point at something a
    human can find on the page. A paragraph is that unit in every document this
    system ingests, and a split that no reader recognises makes a citation unusable
    even when it is technically correct.
    """
    return [block.strip() for block in PARAGRAPH.split(text) if block.strip()]


def chunk_document(
    text: str,
    descriptor: SourceDescriptor,
    *,
    page_of: dict[int, int] | None = None,
) -> list[EvidenceSpan]:
    """Turn raw text into evidence spans. Pure: no clock, no store, no io."""
    document_hash = content_hash(text)
    document_id = uuid5(NAMESPACE, f"document:{descriptor.title}:{document_hash}")
    version_id = uuid5(NAMESPACE, f"version:{document_id}:{descriptor.revision or '-'}")
    spans: list[EvidenceSpan] = []
    for index, block in enumerate(split_paragraphs(text)):
        chunk_id = uuid5(NAMESPACE, f"chunk:{version_id}:{content_hash(block)}:{index}")
        quote = block if len(block) <= MAX_QUOTE else block[: MAX_QUOTE - 1].rstrip() + "…"
        spans.append(
            EvidenceSpan(
                citation=Citation(
                    document_id=document_id,
                    chunk_id=chunk_id,
                    title=descriptor.title,
                    revision=descriptor.revision,
                    page=(page_of or {}).get(index),
                    section=None,
                    quote=quote,
                    source_uri=descriptor.source_uri,
                ),
                chunk_id=chunk_id,
                document_id=document_id,
                document_version_id=version_id,
                corpus_id=descriptor.corpus_id,
                text=block,
                retrieval_score=0.0,
                access_tier=descriptor.access_tier,
                review_state=descriptor.review_state,
                authority=descriptor.authority,
                valid_until=descriptor.valid_until,
            )
        )
    return spans


def read_source(path: Path) -> str:
    """Read a plain-text or markdown source.

    Binary formats are refused rather than half-extracted: a PDF read as bytes
    produces chunks that look like text, cite like text, and mean nothing.
    """
    if path.suffix.lower() not in {".txt", ".md"}:
        raise ValueError(
            f"{path.name}: only .txt and .md are ingested today; "
            "PDF and DOCX need an extraction step that does not exist yet"
        )
    return path.read_text(encoding="utf-8")
