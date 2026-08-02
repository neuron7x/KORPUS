from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    # Corpus membership is part of the evidence, not a lookup table beside it. A span
    # that belongs to no corpus cannot be authorized, so it cannot be indexed.
    corpus_id: UUID
    text: str = Field(min_length=1)
    retrieval_score: float = Field(ge=0, le=1)
    access_tier: AccessTier
    review_state: ReviewState
    authority: AuthorityClass
    valid_until: datetime | None = None
    superseded_by: UUID | None = None

    @field_validator("valid_until")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        """A naive timestamp compared against an aware clock raises TypeError mid-request.

        Ingestion sources hand over both shapes, so the boundary coerces instead of
        trusting: naive input is read as UTC, which is what the corpus records use.
        """
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


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


class SearchHit(BaseModel):
    """One source a reader is allowed to open, with the score that surfaced it."""

    model_config = ConfigDict(frozen=True)

    citation: Citation
    score: float = Field(ge=0, le=1)
    authority: AuthorityClass


class SearchResponse(BaseModel):
    """Browsing the corpus without generating anything.

    The degraded mode SYSTEM.md requires: when the generator is unavailable a reader
    must still be able to reach the source. Same status vocabulary as an answer, so a
    client does not learn a second one.
    """

    trace_id: UUID = Field(default_factory=uuid4)
    status: AnswerStatus
    results: list[SearchHit] = Field(default_factory=list)
    truncated: bool = False
    limitations: list[str] = Field(default_factory=list)


class FeedbackVerdict(StrEnum):
    HELPFUL = "helpful"
    WRONG = "wrong"
    DANGEROUS = "dangerous"
    INCOMPLETE = "incomplete"


class Feedback(BaseModel):
    """A correction from the person who had to act on the answer.

    `dangerous` exists as its own verdict because "wrong" and "would have got someone
    hurt" must not aggregate into one number.
    """

    model_config = ConfigDict(extra="forbid")

    trace_id: UUID
    verdict: FeedbackVerdict
    comment: str | None = Field(default=None, max_length=2000)


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
