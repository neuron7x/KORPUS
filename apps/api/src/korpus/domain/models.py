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
    title: str
    revision: str | None = None
    page: int | None = Field(None, ge=1)
    section: str | None = None
    quote: str = Field(min_length=1, max_length=1200)
    source_uri: str | None = None


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(frozen=True)

    citation: Citation
    retrieval_score: float = Field(ge=0, le=1)
    access_tier: AccessTier
    review_state: ReviewState
    authority: AuthorityClass


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ACCESS_DENIED = "access_denied"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"


class Answer(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    status: AnswerStatus
    text: str
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Query(BaseModel):
    text: str = Field(min_length=3, max_length=4000)
    user_tier: AccessTier = AccessTier.PUBLIC
    corpus_ids: list[UUID] = Field(default_factory=list, max_length=20)
    locale: str = Field(default="uk-UA", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")

