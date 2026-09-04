from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from korpus.application.capability_gateway.contracts import payload_digest
from korpus.application.capability_gateway.errors import CapabilityContractError
from korpus.application.capability_gateway.types import (
    CapabilitySpec,
    EvidenceProfile,
    InvocationContext,
)

DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"


class EvidenceStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class ProvenanceKind(StrEnum):
    INTERNAL = "INTERNAL"
    REMOTE_RESPONSE = "REMOTE_RESPONSE"
    SIGNED_RECEIPT = "SIGNED_RECEIPT"
    SOURCE_EVIDENCE = "SOURCE_EVIDENCE"


class EvidenceBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    invocation_id: UUID
    capability_id: str = Field(min_length=1, max_length=128)
    capability_version: str = Field(min_length=1, max_length=64)
    adapter_id: str = Field(min_length=1, max_length=128)
    adapter_version: str = Field(min_length=1, max_length=64)
    output_digest: str = Field(pattern=DIGEST_PATTERN)


class EvidenceProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ProvenanceKind
    source_refs: list[str] = Field(default_factory=list, max_length=128)
    provider_identity: str | None = Field(default=None, max_length=256)


class EvidenceEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["korpus.evidence-envelope.v1"]
    status: EvidenceStatus
    binding: EvidenceBinding
    provenance: EvidenceProvenance
    observed_at: datetime
    expires_at: datetime | None = None
    reproducible: bool = False
    signature_ref: str | None = Field(default=None, max_length=1024)


def validate_evidence(
    *,
    spec: CapabilitySpec,
    context: InvocationContext,
    output: object,
    evidence: EvidenceEnvelope | None,
    evaluated_at: datetime,
) -> None:
    profile = spec.evidence.profile
    if profile is EvidenceProfile.NONE and evidence is None:
        return
    if evidence is None:
        raise CapabilityContractError("required capability evidence is missing")
    if evidence.status is not EvidenceStatus.VALID:
        raise CapabilityContractError(f"capability evidence status is {evidence.status.value}")
    if evidence.observed_at.tzinfo is None or evaluated_at.tzinfo is None:
        raise CapabilityContractError("evidence timestamps must be timezone-aware")
    if evidence.observed_at > evaluated_at:
        raise CapabilityContractError("evidence observation is in the future")
    if evidence.expires_at is not None:
        if evidence.expires_at.tzinfo is None:
            raise CapabilityContractError("evidence expiry must be timezone-aware")
        if evaluated_at > evidence.expires_at:
            raise CapabilityContractError("capability evidence has expired")

    binding = evidence.binding
    if binding.invocation_id != context.invocation_id:
        raise CapabilityContractError("evidence invocation binding does not match")
    if binding.capability_id != spec.capability_id or binding.capability_version != spec.version:
        raise CapabilityContractError("evidence capability binding does not match")
    if (
        binding.adapter_id != spec.adapter.adapter_id
        or binding.adapter_version != spec.adapter.adapter_version
    ):
        raise CapabilityContractError("evidence adapter binding does not match")
    if binding.output_digest != payload_digest(output):
        raise CapabilityContractError("evidence output digest does not match")

    freshness = spec.evidence.freshness_seconds
    if freshness is not None and evaluated_at - evidence.observed_at > timedelta(seconds=freshness):
        raise CapabilityContractError("capability evidence is stale")

    if profile is EvidenceProfile.PROVIDER_PROVENANCE:
        if evidence.provenance.kind not in {
            ProvenanceKind.REMOTE_RESPONSE,
            ProvenanceKind.SIGNED_RECEIPT,
        }:
            raise CapabilityContractError("provider provenance profile has wrong provenance kind")
        if not evidence.provenance.source_refs:
            raise CapabilityContractError("provider provenance requires source reference")
    elif profile is EvidenceProfile.FACTUAL_EVIDENCE:
        if evidence.provenance.kind is not ProvenanceKind.SOURCE_EVIDENCE:
            raise CapabilityContractError("factual evidence profile requires source evidence")
        if not evidence.provenance.source_refs:
            raise CapabilityContractError("factual evidence requires source references")
    elif profile is EvidenceProfile.SIGNED_RECEIPT:
        if evidence.provenance.kind is not ProvenanceKind.SIGNED_RECEIPT:
            raise CapabilityContractError("signed receipt profile requires signed provenance")
        if evidence.signature_ref is None:
            raise CapabilityContractError("signed receipt profile requires signature reference")
