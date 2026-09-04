from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from korpus.application.capability_gateway.audit import CapabilityAuditSink, InvocationOutcome
from korpus.application.capability_gateway.contracts import payload_digest
from korpus.application.capability_gateway.errors import CapabilityContractError
from korpus.application.capability_gateway.evidence import EvidenceEnvelope
from korpus.application.capability_gateway.policy import CapabilityPolicyDecision
from korpus.application.capability_gateway.types import (
    CapabilitySpec,
    IntegrationRequest,
    InvocationContext,
)
from korpus.domain.models import Identity

_MAX_AUDIT_RECORD_ID_LENGTH = 256


class IntegrationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["korpus.integration-result.v1"] = "korpus.integration-result.v1"
    invocation_id: UUID
    outcome: InvocationOutcome
    output: object | None = None
    evidence: EvidenceEnvelope | None = None
    audit_record_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=_MAX_AUDIT_RECORD_ID_LENGTH,
    )
    error_code: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_returnability_invariants(self) -> IntegrationResult:
        if self.audit_record_id is not None and not self.audit_record_id.strip():
            raise ValueError("audit record identity must be non-blank")
        if self.outcome is InvocationOutcome.SUCCESS:
            if self.audit_record_id is None:
                raise ValueError("successful integration result requires persisted audit identity")
            if self.error_code is not None:
                raise ValueError("successful integration result cannot carry an error code")
            return self
        if self.output is not None or self.evidence is not None:
            raise ValueError("non-success integration result cannot expose output or evidence")
        return self


@dataclass(frozen=True, slots=True)
class InvocationFrame:
    identity: Identity
    request: IntegrationRequest
    started_at: datetime
    spec: CapabilitySpec
    context: InvocationContext
    decision: CapabilityPolicyDecision
    logical_resource: str


@dataclass(frozen=True, slots=True)
class ExecutionMaterial:
    output: object | None = None
    evidence: EvidenceEnvelope | None = None
    idempotency_binding: str | None = None
    provider_receipt: object | None = None


class CapabilityResultEmitter:
    """Single success-return boundary: canonical audit must persist before data is exposed."""

    def __init__(self, audit: CapabilityAuditSink) -> None:
        self._audit = audit

    def emit(
        self,
        frame: InvocationFrame,
        outcome: InvocationOutcome,
        error_code: str | None,
        material: ExecutionMaterial | None = None,
    ) -> IntegrationResult:
        carried = material or ExecutionMaterial()
        try:
            audit_id = self._audit.append(
                identity=frame.identity,
                spec=frame.spec,
                context=frame.context,
                decision=frame.decision,
                logical_resource=frame.logical_resource,
                input_digest=payload_digest(frame.request.input),
                output_digest=_optional_digest(carried.output),
                evidence_digest=_evidence_digest(carried.evidence),
                idempotency_binding=carried.idempotency_binding,
                provider_receipt_digest=_optional_digest(carried.provider_receipt),
                outcome=outcome,
                error_code=error_code,
                started_at=frame.started_at,
                ended_at=datetime.now(frame.started_at.tzinfo),
            )
        except Exception:
            return early_result(
                InvocationOutcome.FAILED,
                "AUDIT_APPEND_FAILED",
                invocation_id=frame.context.invocation_id,
            )
        if not _valid_audit_record_id(audit_id):
            return early_result(
                InvocationOutcome.FAILED,
                "AUDIT_APPEND_FAILED",
                invocation_id=frame.context.invocation_id,
            )

        expose = outcome is InvocationOutcome.SUCCESS
        return IntegrationResult(
            invocation_id=frame.context.invocation_id,
            outcome=outcome,
            output=carried.output if expose else None,
            evidence=carried.evidence if expose else None,
            audit_record_id=audit_id,
            error_code=error_code,
        )


def early_result(
    outcome: InvocationOutcome,
    error_code: str,
    *,
    invocation_id: UUID | None = None,
) -> IntegrationResult:
    return IntegrationResult(
        invocation_id=invocation_id or uuid4(),
        outcome=outcome,
        audit_record_id=None,
        error_code=error_code,
    )


def _valid_audit_record_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= _MAX_AUDIT_RECORD_ID_LENGTH
    )


def _evidence_digest(evidence: EvidenceEnvelope | None) -> str | None:
    if evidence is None:
        return None
    return _optional_digest(evidence.model_dump(mode="json"))


def _optional_digest(value: object | None) -> str | None:
    if value is None:
        return None
    try:
        return payload_digest(value)
    except CapabilityContractError:
        return None
