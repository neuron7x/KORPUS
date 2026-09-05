from __future__ import annotations

from dataclasses import replace

from korpus.application.capability_gateway.adapters import (
    AdapterExecutionResult,
    AdapterOutcomeUnknown,
    AdapterRegistry,
)
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.effects import (
    EffectRecord,
    EffectReservation,
    EffectState,
    assert_effect_transition,
)
from korpus.application.capability_gateway.invoke import CapabilityGateway
from korpus.application.capability_gateway.policy import CapabilityPolicyBridge
from korpus.application.capability_gateway.registry import CapabilityRegistry
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
from korpus.application.policy import PolicyEngine
from korpus.domain.models import Identity


class _Schemas:
    def validate(self, schema_id: str, value: object) -> None:
        del schema_id, value


class _Egress:
    def check(self, **kwargs: object) -> None:
        del kwargs


class _EffectAuthorizer:
    def authorize(self, **kwargs: object) -> bool:
        del kwargs
        return True


class _Ledger:
    def __init__(self, *, fail_target: EffectState | None = None) -> None:
        self.records: dict[tuple[str, str], EffectRecord] = {}
        self.fail_target = fail_target

    def reserve(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        binding_digest: str,
        invocation_id: str,
        capability_id: str,
        capability_version: str,
        logical_resource: str,
        input_digest: str,
    ) -> EffectReservation:
        key = subject_id, idempotency_key
        existing = self.records.get(key)
        if existing is not None:
            return EffectReservation(record=existing, created=False)
        record = EffectRecord(
            subject_id=subject_id,
            idempotency_key=idempotency_key,
            binding_digest=binding_digest,
            invocation_id=invocation_id,
            capability_id=capability_id,
            capability_version=capability_version,
            logical_resource=logical_resource,
            input_digest=input_digest,
            state=EffectState.PENDING,
        )
        self.records[key] = record
        return EffectReservation(record=record, created=True)

    def transition(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected: EffectState,
        target: EffectState,
        provider_reference: str | None = None,
    ) -> EffectRecord:
        if target is self.fail_target:
            raise RuntimeError("simulated durable transition failure")
        key = subject_id, idempotency_key
        current = self.records[key]
        if current.state is not expected:
            raise RuntimeError("compare-and-set failed")
        assert_effect_transition(current.state, target)
        updated = replace(current, state=target, provider_reference=provider_reference)
        self.records[key] = updated
        return updated


class _Audit:
    def __init__(self) -> None:
        self.calls = 0

    def append(self, **kwargs: object) -> str:
        del kwargs
        self.calls += 1
        return f"audit-read-{self.calls}"


class _Adapter:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def execute(self, **kwargs: object) -> AdapterExecutionResult:
        del kwargs
        self.calls += 1
        if self.error is not None:
            raise self.error
        return AdapterExecutionResult(output={"value": "ok"})


def _spec() -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.idempotent.read",
        version="1.0.0",
        description="Read with an explicit idempotency reservation.",
        provider_type=ProviderType.INTERNAL,
        adapter=AdapterSpec(adapter_id="internal.idempotent-read", adapter_version="1.0.0"),
        effect_class=EffectClass.READ_LOCAL,
        input_schema_id="urn:korpus:test:idempotent-read-input:v1",
        output_schema_id="urn:korpus:test:idempotent-read-output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:read",
            resource_mapper="reference_resource_v1",
        ),
        evidence=EvidenceSpec(profile=EvidenceProfile.NONE),
        timeouts=TimeoutSpec(total_ms=1000),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=True),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.NONE,
            max_request_bytes=4096,
            max_response_bytes=4096,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _request() -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.idempotent.read",
        capability_version="1.0.0",
        input={"reference_id": "1"},
        idempotency_key="idem-read-1",
    )


def _gateway(
    *,
    adapter: _Adapter,
    ledger: _Ledger,
) -> tuple[CapabilityGateway, _Audit]:
    adapters = AdapterRegistry()
    adapters.register("internal.idempotent-read", "1.0.0", adapter)
    audit = _Audit()
    gateway = CapabilityGateway(
        registry=CapabilityRegistry([_spec()]),
        policy=CapabilityPolicyBridge(
            PolicyEngine(),
            action_permissions={"integration:reference:read": "answer:read"},
            resource_authorizers={"reference_resource_v1": lambda identity, spec, resource: True},
        ),
        adapters=adapters,
        schemas=_Schemas(),
        resource_mappers={
            "reference_resource_v1": lambda identity, spec, request: (
                f"reference:{request.input['reference_id']}"
            )
        },
        egress=_Egress(),
        effect_authorizer=_EffectAuthorizer(),
        effects=ledger,
        audit=audit,
    )
    return gateway, audit


def _identity() -> Identity:
    return Identity(subject="reader", roles=frozenset({"user"}))


def test_read_timeout_cannot_be_promoted_to_possible_external_effect() -> None:
    ledger = _Ledger()
    adapter = _Adapter(error=AdapterOutcomeUnknown("read transport timed out"))
    gateway, audit = _gateway(adapter=adapter, ledger=ledger)

    first = gateway.invoke(identity=_identity(), request=_request())
    second = gateway.invoke(identity=_identity(), request=_request())

    assert first.outcome is InvocationOutcome.FAILED
    assert first.error_code == "ADAPTER_TIMEOUT"
    assert ledger.records[("reader", "idem-read-1")].state is EffectState.FAILED_KNOWN_NO_EFFECT
    assert second.outcome is InvocationOutcome.FAILED
    assert second.error_code == "IDEMPOTENT_REPLAY_KNOWN_NO_EFFECT"
    assert adapter.calls == 1
    assert audit.calls == 2


def test_successful_idempotent_read_replays_as_completed_not_effect_committed() -> None:
    ledger = _Ledger()
    adapter = _Adapter()
    gateway, _ = _gateway(adapter=adapter, ledger=ledger)

    first = gateway.invoke(identity=_identity(), request=_request())
    second = gateway.invoke(identity=_identity(), request=_request())

    assert first.outcome is InvocationOutcome.SUCCESS
    assert ledger.records[("reader", "idem-read-1")].state is EffectState.COMMITTED
    assert second.outcome is InvocationOutcome.FAILED
    assert second.error_code == "IDEMPOTENT_REPLAY_COMPLETED"
    assert adapter.calls == 1


def test_read_finalize_persistence_failure_is_failed_not_effect_outcome_unknown() -> None:
    ledger = _Ledger(fail_target=EffectState.COMMITTED)
    adapter = _Adapter()
    gateway, _ = _gateway(adapter=adapter, ledger=ledger)

    first = gateway.invoke(identity=_identity(), request=_request())
    second = gateway.invoke(identity=_identity(), request=_request())

    assert first.outcome is InvocationOutcome.FAILED
    assert first.error_code == "INTERNAL_ERROR"
    assert ledger.records[("reader", "idem-read-1")].state is EffectState.PENDING
    assert second.outcome is InvocationOutcome.OUTCOME_UNKNOWN
    assert second.error_code == "IDEMPOTENT_REPLAY_PENDING"
    assert adapter.calls == 1
