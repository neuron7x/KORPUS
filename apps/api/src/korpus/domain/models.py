from __future__ import annotations

from datetime import UTC, date, datetime
from enum import IntEnum, StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccessTier(IntEnum):
    PUBLIC = 0
    AUTHENTICATED = 1
    REVIEWED = 2
    RESTRICTED = 3

    @classmethod
    def parse(cls, value: str | int | "AccessTier") -> "AccessTier":
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(value)
        return cls[value.strip().upper()]

    def label(self) -> str:
        return self.name.lower()


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
    HISTORICAL = "historical"
    UNKNOWN = "unknown"


class Classification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ACCESS_DENIED = "access_denied"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"


class SupportState(StrEnum):
    EXTRACTIVE = "extractive"
    UNSUPPORTED = "unsupported"


class Identity(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject: str = Field(min_length=1, max_length=200)
    roles: frozenset[str] = Field(default_factory=frozenset)
    clearance: AccessTier = AccessTier.PUBLIC
    corpora: frozenset[str] = Field(default_factory=lambda: frozenset({"public"}))

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


class DocumentCreate(BaseModel):
    canonical_title: str = Field(min_length=3, max_length=500)
    corpus_id: str = Field(default="public", pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    issuer: str = Field(min_length=2, max_length=300)
    jurisdiction: str = Field(default="UA", min_length=2, max_length=50)
    document_type: str = Field(default="reference", min_length=2, max_length=100)
    access_tier: AccessTier = AccessTier.PUBLIC
    classification: Classification = Classification.PUBLIC


class VersionCreate(BaseModel):
    revision: str = Field(min_length=1, max_length=120)
    publication_identifier: str | None = Field(default=None, max_length=200)
    source_uri: str | None = Field(default=None, max_length=2000)
    publication_date: date | None = None
    effective_from: date | None = None
    effective_until: date | None = None
    authority: AuthorityClass = AuthorityClass.UNKNOWN
    supersedes_version_id: UUID | None = None

    @field_validator("effective_until")
    @classmethod
    def validate_dates(cls, value: date | None, info: object) -> date | None:
        data = getattr(info, "data", {})
        start = data.get("effective_from") if isinstance(data, dict) else None
        if value is not None and start is not None and value < start:
            raise ValueError("effective_until cannot precede effective_from")
        return value


class DocumentRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    canonical_title: str
    corpus_id: str
    issuer: str
    jurisdiction: str
    document_type: str
    access_tier: AccessTier
    classification: Classification
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DocumentVersionRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    revision: str
    publication_identifier: str | None = None
    source_uri: str | None = None
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    object_key: str
    mime_type: str
    publication_date: date | None = None
    effective_from: date | None = None
    effective_until: date | None = None
    rescinded_at: datetime | None = None
    authority: AuthorityClass
    review_state: ReviewState = ReviewState.QUARANTINED
    supersedes_version_id: UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def is_active(self, as_of: date) -> bool:
        if self.rescinded_at is not None:
            return False
        if self.effective_from is not None and as_of < self.effective_from:
            return False
        return self.effective_until is None or as_of <= self.effective_until


class EvidenceSpanRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    version_id: UUID
    ordinal: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, max_length=500)
    text: str = Field(min_length=1, max_length=12000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RetrievedEvidence(BaseModel):
    span: EvidenceSpanRecord
    document: DocumentRecord
    version: DocumentVersionRecord
    score: float = Field(ge=0, le=1)
    query_coverage: float = Field(ge=0, le=1)


class QueryRequest(BaseModel):
    text: str = Field(min_length=3, max_length=4000)
    corpus_ids: list[str] = Field(default_factory=list, max_length=20)
    as_of: date = Field(default_factory=date.today)
    locale: str = Field(default="uk-UA", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: UUID
    version_id: UUID
    span_id: UUID
    title: str
    revision: str
    page: int | None = None
    section: str | None = None
    quote: str = Field(min_length=1, max_length=1600)
    source_uri: str | None = None
    source_hash: str


class Claim(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1, max_length=2000)
    evidence_span_ids: tuple[UUID, ...] = Field(min_length=1)
    support_state: SupportState = SupportState.EXTRACTIVE
    support_score: float = Field(ge=0, le=1)


class Answer(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    status: AnswerStatus
    text: str
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    retrieval_score: float = Field(ge=0, le=1)
    evidence_coverage: float = Field(ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)
    corpus_release: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewTransition(BaseModel):
    target: ReviewState
    note: str = Field(min_length=3, max_length=2000)


class AuditVerification(BaseModel):
    valid: bool
    event_count: int = Field(ge=0)
    first_invalid_sequence: int | None = None


class IngestResult(BaseModel):
    document: DocumentRecord
    version: DocumentVersionRecord
    span_count: int = Field(ge=0)
    extraction_method: str
    duplicate: bool = False
