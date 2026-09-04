from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from korpus.application.capability_gateway.adapters import (
    AdapterExecutionFailed,
    AdapterKnownNoEffect,
    AdapterOutcomeUnknown,
    AdapterRegistry,
)
from korpus.application.capability_gateway.audit import CapabilityAuditSink, InvocationOutcome
from korpus.application.capability_gateway.context import build_invocation_context
from korpus.application.capability_gateway.contracts import (
    canonical_json_bytes,
    payload_digest,
    validate_request_binding,
)
from korpus.application.capability_gateway.effects import (
    EffectGuard,
    EffectLedger,
    EffectState,
    IdempotencyConflict,
    effectful,
    prepare_effect_guard,
)
from korpus.application.capability_gateway.errors import (
    CapabilityAuthorizationDenied,
    CapabilityContractError,
    CapabilityNotFound,
    CapabilityUnavailable,
)
from korpus.application.capability_gateway.evidence import EvidenceEnvelope, validate_evidence
from korpus.application.capability_gateway.policy import (
    CapabilityPolicyBridge,
    CapabilityPolicyDecision,
)
from korpus.application.capability_gateway.registry import CapabilityRegistry
from korpus.application.capability_gateway.types import (
    CapabilitySpec,
    IntegrationRequest,
    InvocationContext,
)
from korpus.domain.models import Identity

ResourceMapper = Callable[[Identity, CapabilitySpec, IntegrationRequest], str]


class SchemaValidator(Protocol):
    def validate(self, schema_id: str, value: object) -> None: ...


class CapabilityEgressGuard(Protocol):
    def check(
        self,
        *,
        identity: Identity,
        spec: CapabilitySpec,
        request: IntegrationRequest,
        logical_resource: str,
    ) -> None: ...


class EffectAuthorizer(Protocol):
    def authorize(
        self,
        *,
        identity: Identity,
        spec: CapabilitySpec,
        logical_resource: str,
    ) -> bool: ...


class IntegrationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["korpus.integration-result.v1"] = "korpus.integration-result.v1"
    invocation_id: UUID
    outcome: InvocationOutcome
    output: object | None = None
    evidence: EvidenceEnvelope | None = None
    audit_record_id: str | None = Field(default=None, max_length=256)
    error_code: str | None = Field(default=None, max_length=128)


class CapabilityGateway:
    """Fail-closed capability invocation orchestrator.

    The class owns ordering only. Identity, policy, schemas, resource mapping, egress,
    side-effect durability, adapters and audit authority remain injected canonical ports.
    """

    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        policy: CapabilityPolicyBridge,
        adapters: AdapterRegistry,
        schemas: SchemaValidator,
        resource_mappers: Mapping[str, ResourceMapper],
        egress: CapabilityEgressGuard,
        effect_authorizer: EffectAuthorizer,
        effects: EffectLedger,
        audit: CapabilityAuditSink,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._adapters = adapters
        self._schemas = schemas
        self._resource_mappers = dict(resource_mappers)
        self._egress = egress
        self._effect_authorizer = effect_authorizer
        self._effects = effects
        self._audit = audit

    def invoke(self, *, identity: Identity, request: IntegrationRequest) -> IntegrationResult:
        started_at = datetime.now(UTC)
        try:
            spec = self._registry.resolve_exact(request.capability_id, request.capability_version)
        except CapabilityNotFound:
            return self._early_result(InvocationOutcome.DENIED, "CAPABILITY_UNKNOWN")
        except CapabilityUnavailable:
            return self._early_result(InvocationOutcome.DENIED, "CAPABILITY_DISABLED")

        context = build_invocation_context(identity=identity, spec=spec, request_time=started_at)
        mapper = self._resource_mappers.get(spec.authorization.resource_mapper)
        if mapper is None:
            return self._early_result(
                InvocationOutcome.FAILED,
                "RESOURCE_MAPPER_UNKNOWN",
                invocation_id=context.invocation_id,
            )
        try:
            logical_resource = mapper(identity, spec, request)
        except Exception:
            return self._early_result(
                InvocationOutcome.FAILED,
                "RESOURCE_MAPPING_FAILED",
                invocation_id=context.invocation_id,
            )
        if not logical_resource:
            return self._early_result(
                InvocationOutcome.FAILED,
                "RESOURCE_MAPPING_FAILED",
                invocation_id=context.invocation_id,
            )

        try:
            decision = self._policy.authorize(identity, spec)
        except CapabilityAuthorizationDenied:
            return self._early_result(
                InvocationOutcome.DENIED,
                "POLICY_DENIED",
                invocation_id=context.invocation_id,
            )

        try:
            validate_request_binding(request, spec)
            self._schemas.validate(spec.input_schema_id, request.input)
        except (CapabilityContractError, ValueError):
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.REJECTED,
                error_code="INPUT_SCHEMA_INVALID",
            )

        if request.dry_run:
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.REJECTED,
                error_code="DRY_RUN_NOT_ADMITTED",
            )

        try:
            self._egress.check(
                identity=identity,
                spec=spec,
                request=request,
                logical_resource=logical_resource,
            )
        except PermissionError:
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.DENIED,
                error_code="EGRESS_DENIED",
            )
        except Exception:
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.FAILED,
                error_code="EGRESS_POLICY_FAILED",
            )

        explicit_effect_authorized = True
        if effectful(spec):
            try:
                explicit_effect_authorized = self._effect_authorizer.authorize(
                    identity=identity,
                    spec=spec,
                    logical_resource=logical_resource,
                )
            except Exception:
                explicit_effect_authorized = False
            if not explicit_effect_authorized:
                return self._audited_result(
                    identity=identity,
                    spec=spec,
                    context=context,
                    decision=decision,
                    logical_resource=logical_resource,
                    request=request,
                    started_at=started_at,
                    outcome=InvocationOutcome.DENIED,
                    error_code="EFFECT_AUTH_REQUIRED",
                )

        try:
            effect_guard = prepare_effect_guard(
                identity=identity,
                spec=spec,
                request=request,
                logical_resource=logical_resource,
                invocation_id=str(context.invocation_id),
                ledger=self._effects,
                explicit_effect_authorized=explicit_effect_authorized,
            )
        except PermissionError:
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.DENIED,
                error_code="EFFECT_AUTH_REQUIRED",
            )
        except CapabilityContractError:
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.REJECTED,
                error_code="IDEMPOTENCY_REQUIRED",
            )
        except IdempotencyConflict:
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.REJECTED,
                error_code="IDEMPOTENCY_CONFLICT",
            )
        except Exception:
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.FAILED,
                error_code="INTERNAL_ERROR",
            )

        if not effect_guard.should_execute:
            existing = effect_guard.reservation.record if effect_guard.reservation is not None else None
            pending = existing is not None and existing.state in {
                EffectState.PENDING,
                EffectState.OUTCOME_UNKNOWN,
            }
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.OUTCOME_UNKNOWN if pending else InvocationOutcome.FAILED,
                error_code="IDEMPOTENT_REPLAY_REQUIRES_RECONCILIATION",
                idempotency_binding=effect_guard.binding_digest,
            )

        try:
            adapter = self._adapters.resolve(spec)
        except CapabilityNotFound:
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.FAILED,
                error_code="ADAPTER_NOT_REGISTERED",
                idempotency_binding=effect_guard.binding_digest,
            )

        try:
            executed = adapter.execute(
                spec=spec,
                request=request,
                context=context,
                logical_resource=logical_resource,
            )
        except AdapterKnownNoEffect:
            self._transition_if_reserved(effect_guard, EffectState.FAILED_KNOWN_NO_EFFECT)
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.FAILED,
                error_code="ADAPTER_FAILURE",
                idempotency_binding=effect_guard.binding_digest,
            )
        except AdapterOutcomeUnknown:
            self._transition_if_reserved(effect_guard, EffectState.OUTCOME_UNKNOWN)
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.OUTCOME_UNKNOWN,
                error_code="ADAPTER_TIMEOUT",
                idempotency_binding=effect_guard.binding_digest,
            )
        except AdapterExecutionFailed:
            return self._adapter_failure_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                effect_guard=effect_guard,
                error_code="ADAPTER_FAILURE",
            )
        except Exception:
            return self._adapter_failure_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                effect_guard=effect_guard,
                error_code="INTERNAL_ERROR",
            )

        if effect_guard.required:
            self._transition_if_reserved(effect_guard, EffectState.COMMITTED)

        try:
            self._schemas.validate(spec.output_schema_id, executed.output)
            if len(canonical_json_bytes(executed.output)) > spec.data_policy.max_response_bytes:
                raise CapabilityContractError("response payload exceeds capability maximum")
        except (CapabilityContractError, ValueError):
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.FAILED,
                error_code="OUTPUT_SCHEMA_INVALID",
                output=executed.output,
                evidence=executed.evidence,
                idempotency_binding=effect_guard.binding_digest,
                provider_receipt=executed.provider_receipt,
            )

        try:
            validate_evidence(
                spec=spec,
                context=context,
                output=executed.output,
                evidence=executed.evidence,
                evaluated_at=datetime.now(UTC),
            )
        except CapabilityContractError as exc:
            message = str(exc).lower()
            code = "EVIDENCE_STALE" if "stale" in message or "expired" in message else "EVIDENCE_INVALID"
            if "missing" in message:
                code = "EVIDENCE_MISSING"
            return self._audited_result(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                request=request,
                started_at=started_at,
                outcome=InvocationOutcome.ABSTAINED,
                error_code=code,
                output=executed.output,
                evidence=executed.evidence,
                idempotency_binding=effect_guard.binding_digest,
                provider_receipt=executed.provider_receipt,
            )

        return self._audited_result(
            identity=identity,
            spec=spec,
            context=context,
            decision=decision,
            logical_resource=logical_resource,
            request=request,
            started_at=started_at,
            outcome=InvocationOutcome.SUCCESS,
            error_code=None,
            output=executed.output,
            evidence=executed.evidence,
            idempotency_binding=effect_guard.binding_digest,
            provider_receipt=executed.provider_receipt,
        )

    def _adapter_failure_result(
        self,
        *,
        identity: Identity,
        spec: CapabilitySpec,
        context: InvocationContext,
        decision: CapabilityPolicyDecision,
        logical_resource: str,
        request: IntegrationRequest,
        started_at: datetime,
        effect_guard: EffectGuard,
        error_code: str,
    ) -> IntegrationResult:
        if effect_guard.required:
            self._transition_if_reserved(effect_guard, EffectState.OUTCOME_UNKNOWN)
            outcome = InvocationOutcome.OUTCOME_UNKNOWN
        else:
            outcome = InvocationOutcome.FAILED
        return self._audited_result(
            identity=identity,
            spec=spec,
            context=context,
            decision=decision,
            logical_resource=logical_resource,
            request=request,
            started_at=started_at,
            outcome=outcome,
            error_code=error_code,
            idempotency_binding=effect_guard.binding_digest,
        )

    @staticmethod
    def _early_result(
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

    def _transition_if_reserved(self, guard: EffectGuard, target: EffectState) -> None:
        if guard.reservation is None:
            return
        record = guard.reservation.record
        self._effects.transition(
            idempotency_key=record.idempotency_key,
            expected=EffectState.PENDING,
            target=target,
        )

    def _audited_result(
        self,
        *,
        identity: Identity,
        spec: CapabilitySpec,
        context: InvocationContext,
        decision: CapabilityPolicyDecision,
        logical_resource: str,
        request: IntegrationRequest,
        started_at: datetime,
        outcome: InvocationOutcome,
        error_code: str | None,
        output: object | None = None,
        evidence: EvidenceEnvelope | None = None,
        idempotency_binding: str | None = None,
        provider_receipt: object | None = None,
    ) -> IntegrationResult:
        input_digest = payload_digest(request.input)
        output_digest = self._optional_digest(output)
        evidence_digest = self._optional_digest(
            evidence.model_dump(mode="json") if evidence is not None else None
        )
        provider_receipt_digest = self._optional_digest(provider_receipt)
        try:
            audit_id = self._audit.append(
                identity=identity,
                spec=spec,
                context=context,
                decision=decision,
                logical_resource=logical_resource,
                input_digest=input_digest,
                output_digest=output_digest,
                evidence_digest=evidence_digest,
                idempotency_binding=idempotency_binding,
                provider_receipt_digest=provider_receipt_digest,
                outcome=outcome,
                error_code=error_code,
                started_at=started_at,
                ended_at=datetime.now(UTC),
            )
        except Exception:
            return IntegrationResult(
                invocation_id=context.invocation_id,
                outcome=InvocationOutcome.FAILED,
                audit_record_id=None,
                error_code="AUDIT_APPEND_FAILED",
            )

        expose = outcome is InvocationOutcome.SUCCESS
        return IntegrationResult(
            invocation_id=context.invocation_id,
            outcome=outcome,
            output=output if expose else None,
            evidence=evidence if expose else None,
            audit_record_id=audit_id,
            error_code=error_code,
        )

    @staticmethod
    def _optional_digest(value: object | None) -> str | None:
        if value is None:
            return None
        try:
            return payload_digest(value)
        except CapabilityContractError:
            return None
