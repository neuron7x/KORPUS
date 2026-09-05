from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from korpus.application.capability_gateway.adapters import AdapterRegistry
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.effects import (
    EffectGuard,
    EffectRecord,
    EffectReservation,
    EffectState,
)
from korpus.application.capability_gateway.execution import CapabilityExecutor
from korpus.application.capability_gateway.policy import CapabilityPolicyDecision
from korpus.application.capability_gateway.result import CapabilityResultEmitter, InvocationFrame
from korpus.application.capability_gateway.types import (
    ActorType,
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
    InvocationActor,
    InvocationContext,
    ProviderType,
    RetrySpec,
    TimeoutSpec,
)
from korpus.domain.models import Identity


class _Schemas:
    def validate(self, schema_id: str, value: object) -> None:
        del schema_id, value


class _Audit:
    def __init__(self) -> None:
        self.calls = 0

    def append(self, **kwargs: object) -> str:
        del kwargs
        self.calls += 1
        return "audit-adapter-boundary"


class _InvalidResultAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, **kwargs: object) -> object:
        del kwargs
        self.calls += 1
        return {"provider": "returned the wrong runtime type"}


class _Effects:
    def __init__(self) -> None:
        self.targets: list[EffectState] = []

    def transition(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected: EffectState,
        target: EffectState,
        provider_reference: str | None = None,
    ) -> EffectRecord:
        del subject_id, idempotency_key, provider_reference
        assert expected is EffectState.PENDING
        self.targets.append(target)
        return replace(_record(), state=target)


def _spec(effect: EffectClass) -> CapabilitySpec:
    effectful = effect in {
        EffectClass.WRITE_REMOTE,
        EffectClass.TRANSACTIONAL_SIDE_EFFECT,
        EffectClass.PRIVILEGED_ADMIN,
    }
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.adapter.boundary",
        version="1.0.0",
        description="Runtime adapter result-boundary test capability.",
        provider_type=ProviderType.CUSTOM if effectful else ProviderType.INTERNAL,
        adapter=AdapterSpec(adapter_id="boundary.invalid-result", adapter_version="1.0.0"),
        effect_class=effect,
        input_schema_id="urn:korpus:test:adapter-boundary-input:v1",
        output_schema_id="urn:korpus:test:adapter-boundary-output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:read",
            resource_mapper="reference_resource_v1",
            requires_explicit_effect_authorization=effectful,
        ),
        evidence=EvidenceSpec(profile=EvidenceProfile.NONE),
        timeouts=TimeoutSpec(total_ms=1000),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=effectful),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.POLICY_GATED if effectful else DataEgressClass.NONE,
            max_request_bytes=4096,
            max_response_bytes=4096,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _request(*, key: str | None = None) -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.adapter.boundary",
        capability_version="1.0.0",
        input={"reference_id": "1"},
        idempotency_key=key,
    )


def _context() -> InvocationContext:
    return InvocationContext(
        schema_version="korpus.invocation-context.v1",
        invocation_id=UUID("99999999-9999-9999-9999-999999999999"),
        actor=InvocationActor(actor_type=ActorType.USER, subject_id="reader"),
        request_time=datetime(2026, 9, 5, 6, 45, tzinfo=UTC),
        service_release="test",
        policy_context_digest="sha256:" + "0" * 64,
    )


def _decision(spec: CapabilitySpec) -> CapabilityPolicyDecision:
    return CapabilityPolicyDecision(
        capability_id=spec.capability_id,
        capability_version=spec.version,
        action=spec.authorization.action,
        canonical_permission="answer:read",
        allowed=True,
        reason="test_boundary_authorized",
    )


def _frame(spec: CapabilitySpec, request: IntegrationRequest) -> InvocationFrame:
    return InvocationFrame(
        identity=Identity(subject="reader", roles=frozenset({"user"})),
        request=request,
        started_at=datetime(2026, 9, 5, 6, 45, tzinfo=UTC),
        spec=spec,
        context=_context(),
        decision=_decision(spec),
        logical_resource="reference:1",
    )


def _record() -> EffectRecord:
    return EffectRecord(
        subject_id="reader",
        idempotency_key="idem-1",
        binding_digest="sha256:" + "1" * 64,
        invocation_id="99999999-9999-9999-9999-999999999999",
        capability_id="reference.adapter.boundary",
        capability_version="1.0.0",
        logical_resource="reference:1",
        input_digest="sha256:" + "2" * 64,
        state=EffectState.PENDING,
    )


def _executor(adapter: _InvalidResultAdapter, effects: _Effects, audit: _Audit) -> CapabilityExecutor:
    adapters = AdapterRegistry()
    adapters.register("boundary.invalid-result", "1.0.0", adapter)  # type: ignore[arg-type]
    return CapabilityExecutor(
        adapters=adapters,
        schemas=_Schemas(),
        effects=effects,  # type: ignore[arg-type]
        emitter=CapabilityResultEmitter(audit),  # type: ignore[arg-type]
    )


def test_invalid_read_adapter_result_fails_closed_without_attribute_error() -> None:
    adapter = _InvalidResultAdapter()
    effects = _Effects()
    audit = _Audit()
    spec = _spec(EffectClass.READ_LOCAL)
    result = _executor(adapter, effects, audit).execute(
        _frame(spec, _request()),
        EffectGuard(required=False, should_execute=True, binding_digest=None, reservation=None),
    )

    assert adapter.calls == 1
    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "INTERNAL_ERROR"
    assert result.output is None
    assert result.evidence is None
    assert effects.targets == []
    assert audit.calls == 1


def test_invalid_effect_adapter_result_becomes_outcome_unknown_after_dispatch() -> None:
    adapter = _InvalidResultAdapter()
    effects = _Effects()
    audit = _Audit()
    spec = _spec(EffectClass.WRITE_REMOTE)
    record = _record()
    result = _executor(adapter, effects, audit).execute(
        _frame(spec, _request(key="idem-1")),
        EffectGuard(
            required=True,
            should_execute=True,
            binding_digest=record.binding_digest,
            reservation=EffectReservation(record=record, created=True),
        ),
    )

    assert adapter.calls == 1
    assert result.outcome is InvocationOutcome.OUTCOME_UNKNOWN
    assert result.error_code == "INTERNAL_ERROR"
    assert result.output is None
    assert result.evidence is None
    assert effects.targets == [EffectState.OUTCOME_UNKNOWN]
    assert audit.calls == 1
