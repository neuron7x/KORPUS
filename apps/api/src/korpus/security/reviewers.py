from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from korpus.domain.models import AuthorityClass, DocumentRecord, DocumentVersionRecord, ReviewState


class ReviewerGrant(BaseModel):
    credential_id: str = Field(min_length=3, max_length=200)
    stages: frozenset[ReviewState] = Field(min_length=1, max_length=3)
    corpora: frozenset[str] = Field(min_length=1, max_length=64)
    authorities: frozenset[AuthorityClass] = Field(min_length=1, max_length=16)
    valid_from: date | None = None
    valid_until: date | None = None
    revoked: bool = False

    @field_validator("stages")
    @classmethod
    def only_review_stages(cls, values: frozenset[ReviewState]) -> frozenset[ReviewState]:
        allowed = {
            ReviewState.METADATA_REVIEWED,
            ReviewState.CONTENT_REVIEWED,
            ReviewState.APPROVED,
        }
        if not values.issubset(allowed):
            raise ValueError("reviewer grants may authorize review stages only")
        return values

    @model_validator(mode="after")
    def validate_window(self) -> ReviewerGrant:
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("reviewer credential validity window is inverted")
        return self


class ReviewerRegistry(BaseModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    registry_id: str = Field(min_length=3, max_length=120)
    subjects: dict[str, tuple[ReviewerGrant, ...]] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path, expected_sha256: str | None = None) -> ReviewerRegistry:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError("reviewer registry digest mismatch")
        return cls.model_validate_json(raw)

    def authorize(
        self,
        *,
        subject: str,
        target: ReviewState,
        document: DocumentRecord,
        version: DocumentVersionRecord,
        as_of: date | None = None,
    ) -> str:
        current = as_of or date.today()
        grants = self.subjects.get(subject, ())
        for grant in grants:
            if grant.revoked or target not in grant.stages:
                continue
            if (
                document.corpus_id not in grant.corpora
                or version.authority not in grant.authorities
            ):
                continue
            if grant.valid_from and current < grant.valid_from:
                continue
            if grant.valid_until and current > grant.valid_until:
                continue
            return grant.credential_id
        raise PermissionError("subject has no active reviewer credential for this scope")
