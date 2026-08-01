from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from korpus.domain.models import AuthorityClass, Classification, DocumentCreate, VersionCreate


class CorpusOperation(StrEnum):
    INDEX = "index"
    OCR = "ocr"
    CITE = "cite"
    EXTERNAL_EMBEDDING = "external_embedding"
    EXPORT = "export"
    DELETE = "delete"


class CorpusPolicy(BaseModel):
    data_owner: str = Field(min_length=3, max_length=300)
    security_owner: str = Field(min_length=3, max_length=300)
    rights_reference: str = Field(min_length=3, max_length=1000)
    releasability: str = Field(min_length=3, max_length=300)
    allowed_classifications: frozenset[Classification] = Field(min_length=1)
    allowed_authorities: frozenset[AuthorityClass] = Field(min_length=1)
    allowed_operations: frozenset[CorpusOperation] = Field(min_length=1)
    retention_days: int = Field(ge=1, le=36_500)
    legal_hold: bool = False
    declassification_rule: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "CorpusPolicy":
        if CorpusOperation.DELETE in self.allowed_operations and self.legal_hold:
            raise ValueError("delete cannot be enabled while a corpus is under legal hold")
        return self


class CorpusGovernanceProfile(BaseModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    profile_id: str = Field(min_length=3, max_length=120)
    corpora: dict[str, CorpusPolicy] = Field(min_length=1)

    @classmethod
    def load(cls, path: Path, expected_sha256: str | None = None) -> "CorpusGovernanceProfile":
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and actual != expected_sha256:
            raise ValueError("corpus governance profile digest mismatch")
        return cls.model_validate_json(raw)

    def policy_for(self, corpus_id: str) -> CorpusPolicy:
        policy = self.corpora.get(corpus_id)
        if policy is None:
            raise PermissionError("corpus has no approved governance policy")
        return policy

    def authorize_ingestion(
        self,
        document: DocumentCreate,
        version: VersionCreate,
        *,
        ocr_requested: bool,
    ) -> CorpusPolicy:
        policy = self.policy_for(document.corpus_id)
        if CorpusOperation.INDEX not in policy.allowed_operations:
            raise PermissionError("corpus policy does not permit indexing")
        if document.classification not in policy.allowed_classifications:
            raise PermissionError("classification is outside corpus policy")
        if version.authority not in policy.allowed_authorities:
            raise PermissionError("authority class is outside corpus policy")
        if ocr_requested and CorpusOperation.OCR not in policy.allowed_operations:
            raise PermissionError("corpus policy does not permit OCR")
        return policy

    def require_external_embedding(self, corpus_ids: frozenset[str]) -> None:
        if not corpus_ids:
            raise PermissionError("embedding request has no corpus scope")
        denied = sorted(
            corpus_id
            for corpus_id in corpus_ids
            if CorpusOperation.EXTERNAL_EMBEDDING
            not in self.policy_for(corpus_id).allowed_operations
        )
        if denied:
            raise PermissionError(
                f"external embedding is prohibited for corpora: {', '.join(denied)}"
            )
