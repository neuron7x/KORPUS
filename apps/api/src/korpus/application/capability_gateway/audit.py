from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from korpus.application.capability_gateway.contracts import payload_digest
from korpus.application.capability_gateway.policy import CapabilityPolicyDecision
from korpus.application.capability_gateway.types import CapabilitySpec, InvocationContext
from korpus.application.ports import Repository
from korpus.application.request_audit_context import current_request_audit_context
from korpus.domain.models import Identity


class InvocationOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    DENIED = "DENIED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    ABSTAINED = "ABSTAINED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


def capability_policy_decision_ref(
    *,
    identity: Identity,
    spec: CapabilitySpec,
    decision: CapabilityPolicyDecision,
    logical_resource: str,
) -> str:
    return payload_digest(
        {
            "schema": "korpus.capability-policy-decision.v1",
            "subject": identity.subject,
            "capability_id": spec.capability_id,
            "capability_version": spec.version,
            "action": decision.action,
            "canonical_permission": decision.canonical_permission,
            "logical_resource": logical_resource,
            "allowed": decision.allowed,
            "reason": decision.reason,
        }
    )


class CapabilityAuditSink(Protocol):
    def append(
        self,
        *,
        identity: Identity,
        spec: CapabilitySpec,
        context: InvocationContext,
        decision: CapabilityPolicyDecision,
        logical_resource: str,
        input_digest: str,
        output_digest: str | None,
        evidence_digest: str | None,
        idempotency_binding: str | None,
        provider_receipt_digest: str | None,
        outcome: InvocationOutcome,
        error_code: str | None,
        started_at: datetime,
        ended_at: datetime,
    ) -> str: ...


class RepositoryCapabilityAuditSink:
    """Adapter into the canonical repository audit chain.

    The repository remains the authority for sequencing, hashing, persistence and
    external anchoring. This class only supplies a typed capability payload.
    """

    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def append(
        self,
        *,
        identity: Identity,
        spec: CapabilitySpec,
        context: InvocationContext,
        decision: CapabilityPolicyDecision,
        logical_resource: str,
        input_digest: str,
        output_digest: str | None,
        evidence_digest: str | None,
        idempotency_binding: str | None,
        provider_receipt_digest: str | None,
        outcome: InvocationOutcome,
        error_code: str | None,
        started_at: datetime,
        ended_at: datetime,
    ) -> str:
        request_context = current_request_audit_context()
        policy_ref = capability_policy_decision_ref(
            identity=identity,
            spec=spec,
            decision=decision,
            logical_resource=logical_resource,
        )
        payload: dict[str, object] = {
            "schema_version": "korpus.capability-audit.v1",
            "invocation_id": str(context.invocation_id),
            "subject_ref": identity.subject,
            "capability": {
                "id": spec.capability_id,
                "version": spec.version,
                "adapter_id": spec.adapter.adapter_id,
                "adapter_version": spec.adapter.adapter_version,
            },
            "logical_resource": logical_resource,
            "policy_decision_ref": policy_ref,
            "input_digest": input_digest,
            "output_digest": output_digest,
            "evidence_digest": evidence_digest,
            "idempotency_binding": idempotency_binding,
            "provider_receipt_digest": provider_receipt_digest,
            "outcome": outcome.value,
            "error_code": error_code,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "service_release": context.service_release,
            "session_binding": context.actor.session_binding,
            "client_version": request_context.client_version,
        }
        return self._repository.append_audit(
            identity,
            "capability.invoke",
            "capability",
            f"{spec.capability_id}@{spec.version}",
            payload,
        )
