from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import IntEnum, StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CORPUS_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9:_-]{0,63}$")


class AccessTier(IntEnum):
    PUBLIC = 0
    AUTHENTICATED = 1
    REVIEWED = 2
    RESTRICTED = 3

    @classmethod
    def parse(cls, value: str | int | AccessTier) -> AccessTier:
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
    ADVERSARY = "adversary"
    UNKNOWN = "unknown"

    @property
    def is_normative(self) -> bool:
        """Whether a source of this class may govern an answer.

        ADVERSARY exists so that captured or hostile material can be held, searched
        and shown as what it is. It is never normative — the rule lived only in prose
        in docs/governance/DATA_GOVERNANCE.md, where nothing executed it. UNKNOWN is
        not normative either: unclassified provenance is not a source class.
        """
        return self not in {AuthorityClass.ADVERSARY, AuthorityClass.UNKNOWN}


class Classification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"

    @property
    def minimum_tier(self) -> AccessTier:
        return {
            Classification.PUBLIC: AccessTier.PUBLIC,
            Classification.INTERNAL: AccessTier.AUTHENTICATED,
            Classification.RESTRICTED: AccessTier.RESTRICTED,
        }[self]


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ACCESS_DENIED = "access_denied"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"


class SupportState(StrEnum):
    EXTRACTIVE = "extractive"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ExtractedPage:
    """One page of text recovered from a source file.

    A value, not an adapter: it carries no file handle, no parser state and no I/O. It
    lived in `infrastructure/extraction.py` until 2026-08-06, which meant the `Extractor`
    port could not name the thing it returns without the application importing
    infrastructure — the dependency the port exists to remove.
    """

    page: int | None
    text: str


class Identity(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject: str = Field(min_length=1, max_length=200)
    roles: frozenset[str] = Field(default_factory=frozenset, max_length=32)
    clearance: AccessTier = AccessTier.PUBLIC
    corpora: frozenset[str] = Field(default_factory=lambda: frozenset({"public"}), max_length=64)
    compartments: frozenset[str] = Field(default_factory=frozenset, max_length=64)

    @field_validator("subject")
    @classmethod
    def normalize_subject(cls, value: str) -> str:
        value = unicodedata.normalize("NFC", value.strip())
        if any(ord(char) < 32 for char in value):
            raise ValueError("subject contains control characters")
        return value

    @field_validator("roles")
    @classmethod
    def normalize_roles(cls, values: frozenset[str]) -> frozenset[str]:
        normalized = frozenset(value.strip().lower() for value in values)
        if any(not ROLE_PATTERN.fullmatch(value) for value in normalized):
            raise ValueError("invalid role identifier")
        return normalized

    @field_validator("corpora", "compartments")
    @classmethod
    def normalize_corpora(cls, values: frozenset[str]) -> frozenset[str]:
        normalized = frozenset(value.strip().lower() for value in values)
        if any(not CORPUS_ID_PATTERN.fullmatch(value) for value in normalized):
            raise ValueError("invalid corpus or compartment identifier")
        return normalized

    @model_validator(mode="after")
    def validate_identity_scope(self) -> Identity:
        if not self.corpora:
            raise ValueError("identity must have at least one corpus")
        return self

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(role.lower() for role in roles))


class DocumentCreate(BaseModel):
    canonical_title: str = Field(min_length=3, max_length=500)
    corpus_id: str = Field(default="public", pattern=CORPUS_ID_PATTERN.pattern)
    issuer: str = Field(min_length=2, max_length=300)
    jurisdiction: str = Field(default="UA", min_length=2, max_length=50)
    document_type: str = Field(default="reference", min_length=2, max_length=100)
    access_tier: AccessTier = AccessTier.PUBLIC
    classification: Classification = Classification.PUBLIC
    compartments: frozenset[str] = Field(default_factory=frozenset, max_length=64)

    @field_validator("compartments")
    @classmethod
    def validate_compartments(cls, values: frozenset[str]) -> frozenset[str]:
        normalized = frozenset(value.strip().lower() for value in values)
        if any(not CORPUS_ID_PATTERN.fullmatch(value) for value in normalized):
            raise ValueError("invalid compartment identifier")
        return normalized

    @model_validator(mode="after")
    def validate_classification_tier(self) -> DocumentCreate:
        if self.access_tier < self.classification.minimum_tier:
            raise ValueError("access_tier is below classification minimum")
        return self


class VersionCreate(BaseModel):
    revision: str = Field(min_length=1, max_length=120)
    publication_identifier: str | None = Field(default=None, max_length=200)
    source_uri: str | None = Field(default=None, max_length=2000)
    publication_date: date | None = None
    effective_from: date | None = None
    effective_until: date | None = None
    authority: AuthorityClass = AuthorityClass.UNKNOWN
    source_key_id: str | None = Field(default=None, min_length=3, max_length=200)
    source_signature_b64: str | None = Field(default=None, min_length=40, max_length=200)
    supersedes_version_id: UUID | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> VersionCreate:
        if (
            self.effective_until is not None
            and self.effective_from is not None
            and self.effective_until < self.effective_from
        ):
            raise ValueError("effective_until cannot precede effective_from")
        return self


class DocumentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    canonical_title: str
    corpus_id: str
    issuer: str
    jurisdiction: str
    document_type: str
    access_tier: AccessTier
    classification: Classification
    compartments: frozenset[str] = Field(default_factory=frozenset)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DocumentVersionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    source_key_id: str | None = None
    source_signature_b64: str | None = None
    content_fingerprint: str = Field(default="0" * 16, pattern=r"^[a-f0-9]{16}$")
    near_duplicate_of_version_id: UUID | None = None
    near_duplicate_similarity: float | None = Field(default=None, ge=0, le=1)
    near_duplicate_acknowledged_by: str | None = Field(default=None, max_length=200)
    extraction_text_chars: int = Field(default=0, ge=0)
    extraction_alnum_ratio: float = Field(default=0.0, ge=0, le=1)
    extraction_replacement_ratio: float = Field(default=0.0, ge=0, le=1)
    extraction_quality_flags: frozenset[str] = Field(default_factory=frozenset, max_length=16)
    extraction_quality_acknowledged_by: str | None = Field(default=None, max_length=200)
    review_state: ReviewState = ReviewState.QUARANTINED
    supersedes_version_id: UUID | None = None
    state_version: int = Field(default=0, ge=0)
    metadata_reviewed_by: str | None = Field(default=None, max_length=200)
    metadata_reviewer_credential_id: str | None = Field(default=None, max_length=200)
    content_reviewed_by: str | None = Field(default=None, max_length=200)
    content_reviewer_credential_id: str | None = Field(default=None, max_length=200)
    approved_at: datetime | None = None
    approved_by: str | None = Field(default=None, max_length=200)
    approver_credential_id: str | None = Field(default=None, max_length=200)
    is_current: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def in_force_from(self) -> date | None:
        """The first date this version governs, or None if it never says.

        `effective_from = NULL` used to mean "no lower bound", so a version approved
        today was cited as governing on 1900-01-01 and answered "which rules applied on
        that date" with itself. Many orders state only a date of issue, so
        `publication_date` stands in when a separate commencement date is absent; an
        approved version with neither is refused at the approval transition, and this
        property returning None is what the projections use to exclude one that reached
        the database another way.
        """

        return self.effective_from or self.publication_date

    def is_valid_on(self, as_of: date) -> bool:
        lower_bound = self.in_force_from
        if lower_bound is None or as_of < lower_bound:
            return False
        if self.effective_until is not None and as_of > self.effective_until:
            return False
        # De Morgan of the guard `rescinded_at is not None and as_of >= rescinded_at.date()`:
        # the boundary stays exclusive on the rescission day itself (a document is not
        # valid on the date it was rescinded), and `rescinded_at.date()` is still only
        # evaluated when `rescinded_at` is set.
        return self.rescinded_at is None or as_of < self.rescinded_at.date()


class EvidenceSpanRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    version_id: UUID
    ordinal: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, max_length=500)
    text: str = Field(min_length=1, max_length=12000)
    text_hash: str = Field(default="", pattern=r"^(?:|[a-f0-9]{64})$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def derive_text_hash(self) -> EvidenceSpanRecord:
        expected = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.text_hash and self.text_hash != expected:
            raise ValueError("text_hash does not match evidence text")
        if not self.text_hash:
            object.__setattr__(self, "text_hash", expected)
        return self


class RetrievedEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    span: EvidenceSpanRecord
    document: DocumentRecord
    version: DocumentVersionRecord
    score: float = Field(ge=0, le=1)
    query_coverage: float = Field(ge=0, le=1)
    lexical_score: float = Field(default=0.0, ge=0)
    character_score: float = Field(default=0.0, ge=0, le=1)
    authority_bonus: float = Field(default=0.0, ge=0, le=1)
    rank: int = Field(default=0, ge=0)


class OperatorDeclaration(BaseModel):
    """What the operator says about themselves, kept apart from what was verified.

    Access is decided by the OIDC subject and the entitlement profile. These three
    fields are typed on a keyboard, so they are an assertion — NIST SP 800-63-3 calls
    this an unproofed self-asserted attribute, and the distinction is the whole reason
    they are a separate object rather than more fields on `Identity`.

    They travel with the query and enter the audit chain under `declared`, so an
    investigator reading "who asked this" gets both halves: the subject the token
    carried, and the name the person at the keyboard gave. Neither is allowed to stand
    in for the other, and nothing here widens access — a specialty may narrow the
    corpora a query searches, never broaden them.
    """

    model_config = ConfigDict(frozen=True)

    given_name: str = Field(min_length=1, max_length=100)
    family_name: str = Field(min_length=1, max_length=100)
    #: Free text on purpose. A closed list of specialties is a taxonomy nobody in this
    #: repository is entitled to define, and a wrong one would be worse than a typed one.
    specialty: str = Field(min_length=2, max_length=120)

    @field_validator("given_name", "family_name", "specialty")
    @classmethod
    def normalize_declared_text(cls, value: str) -> str:
        value = unicodedata.normalize("NFC", value.strip())
        if any(ord(char) < 32 for char in value):
            raise ValueError("declared field contains control characters")
        return value


class QueryRequest(BaseModel):
    text: str = Field(min_length=3, max_length=4000)
    corpus_ids: list[str] = Field(default_factory=list, max_length=20)
    # Not date.today(): that reads the host's local calendar, so the same question at
    # the same instant was answered differently by two replicas in different zones —
    # reproduced with TZ=Etc/GMT+12 against UTC on 2026-08-03. Validity is a property
    # of the corpus, not of where the process runs.
    as_of: date = Field(default_factory=lambda: datetime.now(UTC).date())
    locale: str = Field(default="uk-UA", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    #: Optional at this layer, required by the interface. Optional here because every
    #: caller that predates it — the eval harness, the CLI, the scale probe — asks
    #: questions with no human at a keyboard, and forcing them to invent a name would
    #: put fabricated declarations into the audit chain.
    declaration: OperatorDeclaration | None = None

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = unicodedata.normalize("NFC", value.strip())
        if any(char == "\x00" for char in value):
            raise ValueError("query contains NUL")
        return value

    @field_validator("corpus_ids")
    @classmethod
    def validate_corpus_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate corpus identifiers")
        if any(not CORPUS_ID_PATTERN.fullmatch(value) for value in normalized):
            raise ValueError("invalid corpus identifier")
        return normalized


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
    quote_start: int = Field(ge=0)
    quote_end: int = Field(gt=0)
    quote_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    #: Hash of the *span* the quote was taken from. `quote_hash` is a hash of the quote
    #: itself and proves only that the quote matches itself; this is the link that ties
    #: the quote to a passage a reader can fetch (`GET /v1/spans/{id}`) and from there
    #: to the document `source_hash` covers.
    span_hash: str = Field(default="", pattern=r"^(?:|[a-f0-9]{64})$")
    source_uri: str | None = Field(default=None, max_length=2000)
    #: The same shape as `DocumentVersionRecord.source_hash`, which has carried
    #: `^[a-f0-9]{64}$` since the beginning. Unconstrained here until 2026-08-06 — on
    #: the field a reader uses to check that the quote came from the document the
    #: system says it did, which is the one place the shape has to be certain.
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_quote_offsets(self) -> Citation:
        if self.quote_end <= self.quote_start:
            raise ValueError("quote_end must be greater than quote_start")
        if hashlib.sha256(self.quote.encode("utf-8")).hexdigest() != self.quote_hash:
            raise ValueError("quote_hash does not match quote")
        return self


class Claim(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1, max_length=2000)
    evidence_span_ids: tuple[UUID, ...] = Field(min_length=1)
    support_state: SupportState = SupportState.EXTRACTIVE
    support_score: float = Field(ge=0, le=1)
    query_coverage: float = Field(ge=0, le=1)


class Answer(BaseModel):
    """The verdict, and everything it rests on, together.

    Frozen since 2026-08-06. The claim this whole system makes is that the text is
    bound to the citations beside it — that binding is decided once, by the policy, and
    a mutable answer lets anything downstream change `text` after `citations` were
    computed. Nothing did; the point is that nothing *can*, and that the model says so
    rather than a convention nobody can check.

    `text` and `corpus_release` carry length bounds for the same reason every other
    outward field does: this crosses the API boundary, and an unbounded string is a
    response size nobody chose.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    status: AnswerStatus
    text: str = Field(max_length=20_000)
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    retrieval_score: float = Field(ge=0, le=1)
    retrieval_score_kind: str = Field(default="ranking_utility", pattern=r"^[a-z0-9_]{3,64}$")
    evidence_coverage: float = Field(ge=0, le=1)
    query_coverage: float = Field(default=0.0, ge=0, le=1)
    decision_reason: str = Field(min_length=1, max_length=500)
    calibration_id: str = Field(min_length=1, max_length=200)
    limitations: list[str] = Field(default_factory=list, max_length=64)
    corpus_release: str = Field(min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewTransition(BaseModel):
    target: ReviewState
    note: str = Field(min_length=12, max_length=2000)
    acknowledge_near_duplicate: bool = False
    acknowledge_extraction_quality: bool = False
    access_tier: AccessTier | None = None

    @model_validator(mode="after")
    def validate_tier_target(self) -> ReviewTransition:
        if self.access_tier is not None and self.target is not ReviewState.APPROVED:
            raise ValueError("access_tier may only be set on approval")
        return self


class RescissionRequest(BaseModel):
    """Withdrawal by the issuing authority — an act, not a review verdict."""

    note: str = Field(min_length=12, max_length=2000)
    rescinded_at: datetime | None = None


class AuditVerification(BaseModel):
    """Two questions, kept apart: is the chain intact, and is the anchor current.

    They used to be one. `valid` was false whenever the external anchor was not exactly
    at the head, so a burst of concurrent appends — the anchor is delivered from an
    outbox, outside the business transaction, by design — made `/v1/audit/verify`
    report the audit as broken while nothing was wrong. Observed on PostgreSQL with 40
    concurrent appends; SQLite serialises writes enough to hide it.

    An anchor *behind* the head is undelivered work and is reported as
    `anchor_pending`. An anchor that disagrees with the event at its own position, or
    that sits ahead of the head, is a real finding: the first means the chain was
    rewritten under it, the second means the database lost committed rows.
    """

    valid: bool
    event_count: int = Field(ge=0)
    head_sequence: int = Field(ge=0)
    anchor_valid: bool
    anchor_pending: int = Field(default=0, ge=0)
    first_invalid_sequence: int | None = None
    reason: str | None = None


class IngestResult(BaseModel):
    document: DocumentRecord
    version: DocumentVersionRecord
    span_count: int = Field(ge=0)
    extraction_method: str
    duplicate: bool = False


class IngestionJobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYABLE = "retryable"
    DEAD_LETTER = "dead_letter"


class IngestionJobKind(StrEnum):
    DOCUMENT = "document"
    VERSION = "version"


class IngestionJobRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    kind: IngestionJobKind
    actor: Identity
    document: DocumentCreate | None = None
    document_id: UUID | None = None
    version: VersionCreate
    filename: str = Field(min_length=1, max_length=500)
    mime_type: str = Field(min_length=1, max_length=200)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    staging_object_key: str = Field(min_length=1, max_length=1000)
    state: IngestionJobState = IngestionJobState.QUEUED
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=20)
    lease_owner: str | None = Field(default=None, max_length=200)
    lease_expires_at: datetime | None = None
    result: IngestResult | None = None
    error_code: str | None = Field(default=None, max_length=200)
    error_detail: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_target(self) -> IngestionJobRecord:
        if self.kind is IngestionJobKind.DOCUMENT:
            if self.document is None or self.document_id is not None:
                raise ValueError("document ingestion job requires document payload only")
        elif self.document is not None or self.document_id is None:
            raise ValueError("version ingestion job requires document_id only")
        if self.state is IngestionJobState.SUCCEEDED and self.result is None:
            raise ValueError("succeeded ingestion job requires result")
        return self
