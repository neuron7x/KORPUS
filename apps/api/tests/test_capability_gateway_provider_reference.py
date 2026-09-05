from __future__ import annotations

from datetime import UTC, datetime

import pytest

from korpus.application.capability_gateway.adapters import (
    AdapterExecutionResult,
    AdapterOutcomeUnknown,
    AdapterRegistry,
)
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.context import build_invocation_context
from korpus.application.capability_gateway.effects import (
    EffectGuard,
    EffectRecord,
    EffectReservation,
    EffectState,
)
from korpus.application.capability_gateway.execution import CapabilityExecutor
from korpus.application.capability_gateway.policy import CapabilityPolicyDecision
from korpus.application.capability_gateway.result import IntegrationResult, InvocationFrame
from korpus.application.capability_gateway.types import (
    AdapterSpec,
    AuthorizationSpec,
    CapabilityLifecycle,
    CapabilitySpec,
    DataEgressClass,
    DataPolicySpec,
    EffectClass,
    EvidenceProfile,
    EvidenceSpec,
    IdempotencySpec,
    IntegrationRequest,
    ProviderType,
    RetrySpec,
    TimeoutSpec,
)
from korpus.domain.models import Identity


class _Schemas:
    def validate(self, schema_id: str, value: object) -> None:
        del schema_id, value


class _Ledger:
    def __init__(self) -> None:
        self.transitions: list[dict[str, object]] = []

    def transition(self, **kwargs: object) -> EffectRecord:
        self.transitions.append(dict(kwargs))
        return EffectRecord(
            subject_id=str(kwargs["subject_id"]),
            idempotency_key=str(kwargs["idempotency_key"]),
            binding_digest="sha256:" + "1" * 64,
            invocation_id="00000000-0000-0000-0000-000000000001",
            capability_id="reference.provider.write",
            capability_version="1.0.0",
            logical_resource="reference:1",
            input_digest="sha256:" + "2" * 64,
            state=EffectState(str(kwargs["target"])),
            provider_reference=(
                str(kwargs["provider_reference"])
                if kwargs.get("provider_reference") is not None
                else None
            ),
        )


class _Emitter:
    def emit(
        self,
        frame: InvocationFrame,
        outcome: InvocationOutcome,
        error_code: str | None,
        material: object | None = None,
    ) -> IntegrationResult:
        del material
        return IntegrationResult(
            invocation_id=frame.context.invocation_id,
            outcome=outcome,
            audit_record_id="audit-provider-reference-1",
            error_code=error_code,
        )


class _SuccessAdapter:
    def execute(self, **kwargs: object) -> AdapterExecutionResult:
        del kwargs
        return AdapterExecutionResult(
            output={"ok": True},
            provider_reference="provider:transaction:42",
        )


class _UnknownAdapter:
    def execute(self, **kwargs: object) -> AdapterExecutionResult:
        del kwargs
        raise AdapterOutcomeUnknown(
            "timeout after dispatch",
            provider_reference="provider:transaction:43",
        )


def _spec() -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.provider.write",
        version="1.0.0",
        description="Provider reference durability test capability.",
        provider_type=ProviderType.CUSTOM,
        adapter=AdapterSpec(adapter_id="custom.provider", adapter_version="1.0.0"),
        effect_class=EffectClass.WRITE_REMOTE,
        input_schema_id="urn:korpus:test:provider-input:v1",
        output_schema_id="urn:korpus:test:provider-output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:write",
            resource_mapper="reference_resource_v1",
            requires_explicit_effect_authorization=True,
        ),
        evidence=EvidenceSpec(profile=EvidenceProfile.NONE),
        timeouts=TimeoutSpec(total_ms=1000),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=True),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.POLICY_GATED,
            max_request_bytes=4096,
            max_response_bytes=4096,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _frame() -> InvocationFrame:
    spec = _spec()
    identity = Identity(subject="writer", roles=frozenset({"admin"}))
    started = datetime(2026, 9, 4, 17, 0, tzinfo=UTC)
    request = IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id=spec.capability_id,
        capability_version=spec.version,
        input={"value": "x"},
        idempotency_key="idem-provider-1",
    )
    context = build_invocation_context(identity=identity, spec=spec, request_time=started)
    return InvocationFrame(
        identity=identity,
        request=request,
        started_at=started,
        spec=spec,
        context=context,
        decision=CapabilityPolicyDecision(
            capability_id=spec.capability_id,
            capability_version=spec.version,
            action=spec.authorization.action,
            canonical_permission="answer:read",
            allowed=True,
            reason="canonical_policy_and_resource_allowed",
        ),
        logical_resource="reference:1",
    )


def _guard(frame: InvocationFrame) -> EffectGuard:
    record = EffectRecord(
        subject_id=frame.identity.subject,
        idempotency_key="idem-provider-1",
        binding_digest="sha256:" + "1" * 64,
        invocation_id=str(frame.context.invocation_id),
        capability_id=frame.spec.capability_id,
        capability_version=frame.spec.version,
        logical_resource=frame.logical_resource,
        input_digest="sha256:" + "2" * 64,
        state=EffectState.PENDING,
    )
    return EffectGuard(
        required=True,
        should_execute=True,
        binding_digest=record.binding_digest,
        reservation=EffectReservation(record=record, created=True),
    )


def _executor(adapter: object, ledger: _Ledger) -> CapabilityExecutor:
    adapters = AdapterRegistry()
    adapters.register("custom.provider", "1.0.0", adapter)  # type: ignore[arg-type]
    return CapabilityExecutor(
        adapters=adapters,
        schemas=_Schemas(),
        effects=ledger,
        emitter=_Emitter(),  # type: ignore[arg-type]
    )


def test_successful_effect_persists_provider_reference_with_commit() -> None:
    frame = _frame()
    ledger = _Ledger()

    result = _executor(_SuccessAdapter(), ledger).execute(frame, _guard(frame))

    assert result.outcome is InvocationOutcome.SUCCESS
    assert len(ledger.transitions) == 1
    assert ledger.transitions[0]["target"] is EffectState.COMMITTED
    assert ledger.transitions[0]["provider_reference"] == "provider:transaction:42"


def test_ambiguous_effect_persists_reference_for_reconciliation() -> None:
    frame = _frame()
    ledger = _Ledger()

    result = _executor(_UnknownAdapter(), ledger).execute(frame, _guard(frame))

    assert result.outcome is InvocationOutcome.OUTCOME_UNKNOWN
    assert result.error_code == "ADAPTER_TIMEOUT"
    assert len(ledger.transitions) == 1
    assert ledger.transitions[0]["target"] is EffectState.OUTCOME_UNKNOWN
    assert ledger.transitions[0]["provider_reference"] == "provider:transaction:43"


@pytest.mark.parametrize("value", ["", "   ", "x" * 513])
def test_provider_reference_must_be_bounded_nonblank(value: str) -> None:
    with pytest.raises(ValueError, match="provider reference"):
        AdapterExecutionResult(output={"ok": True}, provider_reference=value)
    with pytest.raises(ValueError, match="provider reference"):
        AdapterOutcomeUnknown("ambiguous", provider_reference=value)
