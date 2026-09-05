from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from korpus.application.capability_gateway.adapters import (
    AdapterExecutionFailed,
    AdapterExecutionResult,
    AdapterKnownNoEffect,
    AdapterOutcomeUnknown,
    AdapterRegistry,
)
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.contracts import canonical_json_bytes
from korpus.application.capability_gateway.effects import (
    EffectGuard,
    EffectLedger,
    EffectState,
    effectful,
)
from korpus.application.capability_gateway.errors import CapabilityContractError, CapabilityNotFound
from korpus.application.capability_gateway.evidence import (
    CapabilityEvidenceBindingMismatch,
    CapabilityEvidenceMissing,
    CapabilityEvidenceStale,
    validate_evidence,
)
from korpus.application.capability_gateway.result import (
    CapabilityResultEmitter,
    ExecutionMaterial,
    IntegrationResult,
    InvocationFrame,
)


class SchemaValidator(Protocol):
    def validate(self, schema_id: str, value: object) -> None: ...


class CapabilityExecutor:
    """Post-authorization execution engine with explicit effect/result separation."""

    def __init__(
        self,
        *,
        adapters: AdapterRegistry,
        schemas: SchemaValidator,
        effects: EffectLedger,
        emitter: CapabilityResultEmitter,
    ) -> None:
        self._adapters = adapters
        self._schemas = schemas
        self._effects = effects
        self._emitter = emitter

    def validate_input(self, schema_id: str, value: object) -> None:
        self._schemas.validate(schema_id, value)

    def execute(self, frame: InvocationFrame, guard: EffectGuard) -> IntegrationResult:
        executed = self._call_adapter(frame, guard)
        if isinstance(executed, IntegrationResult):
            return executed
        if guard.required and not self._transition(
            guard,
            EffectState.COMMITTED,
            provider_reference=executed.provider_reference,
        ):
            return self._emitter.emit(
                frame,
                InvocationOutcome.OUTCOME_UNKNOWN if effectful(frame.spec) else InvocationOutcome.FAILED,
                "INTERNAL_ERROR",
                self._material(executed, guard),
            )
        invalid_output = self._validate_output(frame, guard, executed)
        if invalid_output is not None:
            return invalid_output
        return self._validate_evidence(frame, guard, executed)

    def _call_adapter(
        self,
        frame: InvocationFrame,
        guard: EffectGuard,
    ) -> AdapterExecutionResult | IntegrationResult:
        try:
            adapter = self._adapters.resolve(frame.spec)
        except CapabilityNotFound:
            return self._emitter.emit(
                frame,
                InvocationOutcome.FAILED,
                "ADAPTER_NOT_REGISTERED",
                ExecutionMaterial(idempotency_binding=guard.binding_digest),
            )
        try:
            executed = adapter.execute(
                spec=frame.spec,
                request=frame.request,
                context=frame.context,
                logical_resource=frame.logical_resource,
            )
        except AdapterKnownNoEffect:
            return self._known_no_effect(frame, guard)
        except AdapterOutcomeUnknown as exc:
            if effectful(frame.spec):
                return self._unknown_effect(
                    frame,
                    guard,
                    "ADAPTER_TIMEOUT",
                    provider_reference=exc.provider_reference,
                )
            return self._known_no_effect(
                frame,
                guard,
                error_code="ADAPTER_TIMEOUT",
                provider_reference=exc.provider_reference,
            )
        except AdapterExecutionFailed as exc:
            return self._adapter_failure(
                frame,
                guard,
                "ADAPTER_FAILURE",
                provider_reference=exc.provider_reference,
            )
        except Exception:
            return self._adapter_failure(frame, guard, "INTERNAL_ERROR")
        if not isinstance(executed, AdapterExecutionResult):
            # Protocol typing is not runtime proof. A provider adapter may be buggy or
            # compromised; after dispatch an effectful operation must become ambiguous
            # rather than escaping as AttributeError or being treated as success.
            return self._adapter_failure(frame, guard, "INTERNAL_ERROR")
        return executed

    def _known_no_effect(
        self,
        frame: InvocationFrame,
        guard: EffectGuard,
        *,
        error_code: str = "ADAPTER_FAILURE",
        provider_reference: str | None = None,
    ) -> IntegrationResult:
        transitioned = self._transition(
            guard,
            EffectState.FAILED_KNOWN_NO_EFFECT,
            provider_reference=provider_reference,
        )
        code = error_code if transitioned else "INTERNAL_ERROR"
        return self._emitter.emit(
            frame,
            InvocationOutcome.FAILED,
            code,
            ExecutionMaterial(idempotency_binding=guard.binding_digest),
        )

    def _unknown_effect(
        self,
        frame: InvocationFrame,
        guard: EffectGuard,
        error_code: str,
        *,
        provider_reference: str | None = None,
    ) -> IntegrationResult:
        transitioned = self._transition(
            guard,
            EffectState.OUTCOME_UNKNOWN,
            provider_reference=provider_reference,
        )
        code = error_code if transitioned else "INTERNAL_ERROR"
        return self._emitter.emit(
            frame,
            InvocationOutcome.OUTCOME_UNKNOWN,
            code,
            ExecutionMaterial(idempotency_binding=guard.binding_digest),
        )

    def _adapter_failure(
        self,
        frame: InvocationFrame,
        guard: EffectGuard,
        error_code: str,
        *,
        provider_reference: str | None = None,
    ) -> IntegrationResult:
        if effectful(frame.spec):
            return self._unknown_effect(
                frame,
                guard,
                error_code,
                provider_reference=provider_reference,
            )
        if guard.required:
            return self._known_no_effect(
                frame,
                guard,
                error_code=error_code,
                provider_reference=provider_reference,
            )
        return self._emitter.emit(frame, InvocationOutcome.FAILED, error_code)

    def _validate_output(
        self,
        frame: InvocationFrame,
        guard: EffectGuard,
        executed: AdapterExecutionResult,
    ) -> IntegrationResult | None:
        material = self._material(executed, guard)
        try:
            self._schemas.validate(frame.spec.output_schema_id, executed.output)
            if len(canonical_json_bytes(executed.output)) > frame.spec.data_policy.max_response_bytes:
                raise CapabilityContractError("response payload exceeds capability maximum")
        except (CapabilityContractError, ValueError):
            return self._emitter.emit(
                frame,
                InvocationOutcome.FAILED,
                "OUTPUT_SCHEMA_INVALID",
                material,
            )
        except Exception:
            return self._emitter.emit(frame, InvocationOutcome.FAILED, "INTERNAL_ERROR", material)
        return None

    def _validate_evidence(
        self,
        frame: InvocationFrame,
        guard: EffectGuard,
        executed: AdapterExecutionResult,
    ) -> IntegrationResult:
        material = self._material(executed, guard)
        try:
            validate_evidence(
                spec=frame.spec,
                context=frame.context,
                output=executed.output,
                evidence=executed.evidence,
                evaluated_at=datetime.now(UTC),
            )
        except CapabilityContractError as exc:
            outcome, code = _evidence_failure_semantics(exc)
            return self._emitter.emit(frame, outcome, code, material)
        except Exception:
            return self._emitter.emit(frame, InvocationOutcome.FAILED, "INTERNAL_ERROR", material)
        return self._emitter.emit(frame, InvocationOutcome.SUCCESS, None, material)

    def _transition(
        self,
        guard: EffectGuard,
        target: EffectState,
        *,
        provider_reference: str | None = None,
    ) -> bool:
        if guard.reservation is None:
            return True
        record = guard.reservation.record
        try:
            self._effects.transition(
                subject_id=record.subject_id,
                idempotency_key=record.idempotency_key,
                expected=EffectState.PENDING,
                target=target,
                provider_reference=provider_reference,
            )
        except Exception:
            return False
        return True

    @staticmethod
    def _material(executed: AdapterExecutionResult, guard: EffectGuard) -> ExecutionMaterial:
        return ExecutionMaterial(
            output=executed.output,
            evidence=executed.evidence,
            idempotency_binding=guard.binding_digest,
            provider_receipt=executed.provider_receipt,
        )


def _evidence_failure_semantics(
    error: CapabilityContractError,
) -> tuple[InvocationOutcome, str]:
    if isinstance(error, CapabilityEvidenceBindingMismatch):
        return InvocationOutcome.FAILED, "EVIDENCE_SUBJECT_MISMATCH"
    if isinstance(error, CapabilityEvidenceMissing):
        return InvocationOutcome.ABSTAINED, "EVIDENCE_MISSING"
    if isinstance(error, CapabilityEvidenceStale):
        return InvocationOutcome.ABSTAINED, "EVIDENCE_STALE"
    return InvocationOutcome.ABSTAINED, "EVIDENCE_INVALID"
