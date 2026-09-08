from __future__ import annotations

from dataclasses import replace
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
    InvalidEffectTransition,
    attest_effect_transition,
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
                InvocationOutcome.OUTCOME_UNKNOWN
                if effectful(frame.spec)
                else InvocationOutcome.FAILED,
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
            # Resolution failed before dispatch. This proves the provider was not invoked,
            # so a durable reservation must not remain PENDING/ambiguous.
            return self._known_no_effect(
                frame,
                guard,
                error_code="ADAPTER_NOT_REGISTERED",
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
        except Exception:  # noqa: BLE001 - third-party adapter code, no nameable base
            # `adapter` is a CapabilityAdapter Protocol implemented outside this package:
            # httpx-based HTTP readers, MCP clients, internal callables and test doubles all
            # qualify, and naming a base would mean importing every provider SDK the gateway
            # is designed not to depend on. Post-dispatch the outcome is genuinely ambiguous,
            # so an unnamed provider fault must degrade through _adapter_failure (which turns
            # it into OUTCOME_UNKNOWN for effectful specs) rather than escape as a traceback.
            # test_capability_gateway_boundary_normalization drives OSError through here.
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
        except (CapabilityContractError, ValueError):
            return self._emitter.emit(
                frame,
                InvocationOutcome.FAILED,
                "OUTPUT_SCHEMA_INVALID",
                material,
            )
        except Exception:  # noqa: BLE001 - injected SchemaValidator port, no nameable base
            # `schemas` is a SchemaValidator Protocol; the validators inside it are caller-owned
            # callables (jsonschema, pydantic, hand-written predicates). The blind catch is now
            # scoped to exactly that foreign call — the size check below no longer shares it.
            return self._emitter.emit(frame, InvocationOutcome.FAILED, "INTERNAL_ERROR", material)
        try:
            oversized = (
                len(canonical_json_bytes(executed.output))
                > frame.spec.data_policy.max_response_bytes
            )
        except CapabilityContractError:
            # canonical_json_bytes is this package's own encoder and has exactly one failure:
            # adapter output that is not canonical JSON. That is a schema fault, not an
            # internal one, which is why it keeps the OUTPUT_SCHEMA_INVALID projection.
            # The output is dropped because it has just been PROVEN undigestible: carried
            # into the emitter it fails there too, and this verdict degrades to a bare
            # INTERNAL_ERROR with no audit row at all (measured 08.09.2026). A non-SUCCESS
            # result never exposes output, so nothing is lost.
            return self._emitter.emit(
                frame,
                InvocationOutcome.FAILED,
                "OUTPUT_SCHEMA_INVALID",
                replace(material, output=None),
            )
        if oversized:
            return self._emitter.emit(
                frame,
                InvocationOutcome.FAILED,
                "OUTPUT_SCHEMA_INVALID",
                material,
            )
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
        except (AttributeError, OverflowError, TypeError, ValueError):
            # validate_evidence is this package's own code, so its failure set is closed — but
            # it reads data the adapter supplied. AdapterExecutionResult is a plain dataclass:
            # `evidence` is annotated EvidenceEnvelope | None and never checked at runtime, so
            # a non-envelope object yields AttributeError. A tzinfo whose utcoffset() is None
            # survives the timezone guard and makes the datetime comparison raise TypeError.
            # An unbounded freshness_seconds (Field(ge=0), no upper bound) makes timedelta()
            # raise OverflowError. ValueError covers out-of-domain values from the same data.
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
            updated = self._effects.transition(
                subject_id=record.subject_id,
                idempotency_key=record.idempotency_key,
                expected=EffectState.PENDING,
                target=target,
                provider_reference=provider_reference,
            )
        except Exception:  # noqa: BLE001 - injected durable EffectLedger port
            # `effects` is an EffectLedger Protocol backed by the durable store. Its failures
            # are database driver exceptions this application layer must not import, and a
            # compare-and-set that loses the race is a legitimate False, not a crash.
            return False
        try:
            attest_effect_transition(
                record,
                updated,
                target=target,
                provider_reference=provider_reference,
            )
        except InvalidEffectTransition:
            # This is the half that used to hide inside the blind catch above: the ledger
            # answered, and OUR attestation refused the answer (wrong state, mutated binding,
            # mismatched provider reference, or a smuggled reconciliation disposition).
            # It is one named class, and conflating it with a dead database made a real
            # defect in this PR indistinguishable from an outage.
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
