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
from korpus.application.capability_gateway.invoke import _replay_semantics
from korpus.application.capability_gateway.policy import CapabilityPolicyDecision
from korpus.application.capability_gateway.result import CapabilityResultEmitter, InvocationFrame
from korpus.application.capability_gateway.types import (
    AdapterSpec,
    ActorType,
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


class _Ledger:
    def __init__(self, record: EffectRecord) -> None:
        self.record = record
        self.transitions: list[EffectState] = []

    def transition(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected: EffectState,
        target: EffectState,
        provider_reference: str | None = None,
    ) -> EffectRecord:
        assert subject_id == self.record.subject_id
        assert idempotency_key == self.record.idempotency_key
        assert expected is EffectState.PENDING
        self.transitions.append(target)
        self.record = replace(
            self.record,
            state=target,
            provider_reference=provider_reference,
        )
        return self.record


class _Audit:
    def __init__(self) -> None:
        self.calls = 0

    def append(self, **kwargs: object) -> str:
        del kwargs
        self.calls += 1
        return "audit-missing-adapter-1"


def _spec() -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.effect.missing-adapter",
        version="1.0.0",
        description="Effectful runtime missing-adapter state control.",
        provider_type=ProviderType.CUSTOM,
        adapter=AdapterSpec(adapter_id="custom.missing", adapter_version="1.0.0"),
        effect_class=EffectClass.WRITE_REMOTE,
        input_schema_id="urn:korpus:test:missing-adapter-input:v1",
        output_schema_id="urn:korpus:test:missing-adapter-output:v1",
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


def _frame(spec: CapabilitySpec) -> InvocationFrame:
    request = IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id=spec.capability_id,
        capability_version=spec.version,
        input={"reference_id": "1"},
        idempotency_key="idem-missing-adapter",
    )
    context = InvocationContext(
        schema_version="korpus.invocation-context.v1",
        invocation_id=UUID("11111111-1111-1111-1111-111111111111"),
        actor=InvocationActor(actor_type=ActorType.USER, subject_id="writer"),
        request_time=datetime(2026, 9, 5, 11, 30, tzinfo=UTC),
        service_release="0.9.7",
        policy_context_digest="sha256:" + "0" * 64,
    )
    decision = CapabilityPolicyDecision(
        capability_id=spec.capability_id,
        capability_version=spec.version,
        action=spec.authorization.action,
        canonical_permission="answer:read",
        allowed=True,
        reason="canonical_policy_and_resource_allowed",
    )
    return InvocationFrame(
        identity=Identity(subject="writer", roles=frozenset({"admin"})),
        request=request,
        started_at=context.request_time,
        spec=spec,
        context=context,
        decision=decision,
        logical_resource="reference:1",
    )


def test_missing_adapter_after_reservation_is_known_no_effect_not_ambiguous() -> None:
    spec = _spec()
    frame = _frame(spec)
    record = EffectRecord(
        subject_id="writer",
        idempotency_key="idem-missing-adapter",
        binding_digest="sha256:" + "1" * 64,
        invocation_id=str(frame.context.invocation_id),
        capability_id=spec.capability_id,
        capability_version=spec.version,
        logical_resource=frame.logical_resource,
        input_digest="sha256:" + "2" * 64,
        state=EffectState.PENDING,
    )
    guard = EffectGuard(
        required=True,
        should_execute=True,
        binding_digest=record.binding_digest,
        reservation=EffectReservation(record=record, created=True),
    )
    ledger = _Ledger(record)
    audit = _Audit()
    executor = CapabilityExecutor(
        adapters=AdapterRegistry(),
        schemas=_Schemas(),
        effects=ledger,  # type: ignore[arg-type]
        emitter=CapabilityResultEmitter(audit),  # type: ignore[arg-type]
    )

    result = executor.execute(frame, guard)

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "ADAPTER_NOT_REGISTERED"
    assert result.output is None
    assert ledger.transitions == [EffectState.FAILED_KNOWN_NO_EFFECT]
    assert ledger.record.state is EffectState.FAILED_KNOWN_NO_EFFECT
    assert audit.calls == 1

    replay_outcome, replay_code = _replay_semantics(ledger.record)
    assert replay_outcome is InvocationOutcome.FAILED
    assert replay_code == "IDEMPOTENT_REPLAY_KNOWN_NO_EFFECT"
