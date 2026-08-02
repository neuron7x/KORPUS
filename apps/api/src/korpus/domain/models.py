from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class AccessTier(StrEnum):
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    REVIEWED = "reviewed"
    RESTRICTED = "restricted"


class ReviewState(StrEnum):
    QUARANTINED = "quarantined"
    METADATA_REVIEWED = "metadata_reviewed"
    CONTENT_REVIEWED = "content_reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


class AuthorityClass(StrEnum):
    OFFICIAL_UA = "official_ua"
    OFFICIAL_ALLIED = "official_allied"
    MANUFACTURER = "manufacturer"
    APPROVED_TRAINING = "approved_training"
    ANALYTICAL = "analytical"
    ADVERSARY = "adversary"
    HISTORICAL = "historical"
    UNKNOWN = "unknown"


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: UUID
    # A citation targets an immutable chunk, never a mutable filename (DATA_MODEL.md).
    chunk_id: UUID
    title: str = Field(min_length=1)
    revision: str | None = None
    page: int | None = Field(None, ge=1)
    section: str | None = None
    quote: str = Field(min_length=1, max_length=1200)
    source_uri: str | None = None


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(frozen=True)

    citation: Citation
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    text: str = Field(min_length=1)
    retrieval_score: float = Field(ge=0, le=1)
    access_tier: AccessTier
    review_state: ReviewState
    authority: AuthorityClass
    valid_until: datetime | None = None
    superseded_by: UUID | None = None


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ACCESS_DENIED = "access_denied"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"


class Claim(BaseModel):
    """One externally checkable assertion plus the evidence that carries it.

    `citation_indexes` point into `Answer.citations`. A claim with an empty tuple is
    unsupported by construction, which is exactly what the verifier looks for.
    """

    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1, max_length=2000)
    citation_indexes: tuple[int, ...] = ()


class Answer(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trace_id: UUID = Field(default_factory=uuid4)
    status: AnswerStatus
    text: str
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    citation_coverage: float = Field(default=0.0, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Query(BaseModel):
    """Client-supplied request.

    Deliberately carries no tier: authority over what a caller may read is derived
    server-side from the authenticated principal (ADR-0004, ADR-0005). A client that
    could name its own tier would hold its own access control.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=3, max_length=4000)
    corpus_ids: list[UUID] = Field(default_factory=list, max_length=20)
    locale: str = Field(default="uk-UA", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
