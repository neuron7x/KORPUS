from __future__ import annotations

from dataclasses import replace

from korpus.application.capability_gateway.adapters import AdapterExecutionResult, AdapterRegistry
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.effects import (
    EffectRecord,
    EffectReservation,
    EffectState,
    assert_effect_transition,
)
from korpus.application.capability_gateway.invoke import CapabilityGateway, CapabilityGatewayPorts
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
from korpus.application.capability_gateway.validation import ExactSchemaRegistry
from korpus.application.policy import PolicyEngine
from korpus.domain.models import Identity


class _Adapter:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, **kwargs: object) -> AdapterExecutionResult:
        del kwargs
        self.calls += 1
        return AdapterExecutionResult(output={"ok": True})


class _Egress:
    def check(self, **kwargs: object) -> None:
        del kwargs


class _EffectAuthorizer:
    def authorize(self, **kwargs: object) -> bool:
        del kwargs
        return True


class _Audit:
    def append(self, **kwargs: object) -> str:
        del kwargs
        return "audit-1"


class _Ledger:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], EffectRecord] = {}

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
        key = subject_id, idempotency_key
        current = self.records[key]
        if current.state is not expected:
            raise RuntimeError("compare-and-set failed")
        assert_effect_transition(current.state, target)
        updated = replace(current, state=target, provider_reference=provider_reference)
        self.records[key] = updated
        return updated


def _spec(capability_id: str, *, effectful: bool = False) -> CapabilitySpec:
    suffix = capability_id.rsplit(".", 1)[-1]
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id=capability_id,
        version="1.0.0",
        description=f"Composition snapshot test capability {capability_id}.",
        provider_type=ProviderType.CUSTOM if effectful else ProviderType.INTERNAL,
        adapter=AdapterSpec(adapter_id=f"snapshot.{suffix}", adapter_version="1.0.0"),
        effect_class=EffectClass.WRITE_REMOTE if effectful else EffectClass.READ_LOCAL,
        input_schema_id=f"urn:korpus:test:snapshot:{suffix}:input:v1",
        output_schema_id=f"urn:korpus:test:snapshot:{suffix}:output:v1",
        authorization=AuthorizationSpec(
            action=f"integration:snapshot:{suffix}",
            resource_mapper="snapshot_resource_v1",
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


def _request(spec: CapabilitySpec) -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id=spec.capability_id,
        capability_version=spec.version,
        input={"id": "1"},
        idempotency_key="idem-1" if spec.idempotency.required else None,
    )


def _gateway(
    *,
    registry: CapabilityRegistry,
    adapters: AdapterRegistry,
    schemas: ExactSchemaRegistry,
    action_permissions: dict[str, str],
) -> CapabilityGateway:
    policy = CapabilityPolicyBridge(
        PolicyEngine(),
        action_permissions=action_permissions,
        resource_authorizers={
            "snapshot_resource_v1": lambda identity, spec, resource: True,
        },
    )
    return CapabilityGateway(
        CapabilityGatewayPorts(
            registry=registry,
            policy=policy,
            adapters=adapters,
            schemas=schemas,
            resource_mappers={
                "snapshot_resource_v1": lambda identity, spec, request: (
                    f"snapshot:{request.input['id']}"
                )
            },
            egress=_Egress(),
            effect_authorizer=_EffectAuthorizer(),
            effects=_Ledger(),
            audit=_Audit(),
        )
    )


def _register_schemas(schemas: ExactSchemaRegistry, spec: CapabilitySpec) -> None:
    schemas.register(spec.input_schema_id, lambda value: None)
    schemas.register(spec.output_schema_id, lambda value: None)


def _identity() -> Identity:
    return Identity(subject="reader", roles=frozenset({"user"}))


def test_post_construction_capability_registration_cannot_widen_runtime_surface() -> None:
    baseline = _spec("reference.snapshot.read")
    injected = _spec("reference.snapshot.write", effectful=True)
    registry = CapabilityRegistry([baseline])
    adapters = AdapterRegistry()
    baseline_adapter = _Adapter()
    injected_adapter = _Adapter()
    adapters.register(
        baseline.adapter.adapter_id,
        baseline.adapter.adapter_version,
        baseline_adapter,
    )
    adapters.register(
        injected.adapter.adapter_id,
        injected.adapter.adapter_version,
        injected_adapter,
    )
    schemas = ExactSchemaRegistry()
    _register_schemas(schemas, baseline)
    _register_schemas(schemas, injected)
    gateway = _gateway(
        registry=registry,
        adapters=adapters,
        schemas=schemas,
        action_permissions={
            baseline.authorization.action: "answer:read",
            injected.authorization.action: "answer:read",
        },
    )

    # The caller-owned registry remains mutable, but the already-admitted gateway does not.
    registry.register(injected)
    result = gateway.invoke(identity=_identity(), request=_request(injected))

    assert result.outcome is InvocationOutcome.DENIED
    assert result.error_code == "CAPABILITY_UNKNOWN"
    assert injected_adapter.calls == 0


def test_post_construction_adapter_registration_cannot_make_capability_executable() -> None:
    spec = _spec("reference.snapshot.read")
    registry = CapabilityRegistry([spec])
    adapters = AdapterRegistry()
    schemas = ExactSchemaRegistry()
    _register_schemas(schemas, spec)
    gateway = _gateway(
        registry=registry,
        adapters=adapters,
        schemas=schemas,
        action_permissions={spec.authorization.action: "answer:read"},
    )
    late_adapter = _Adapter()

    adapters.register(spec.adapter.adapter_id, spec.adapter.adapter_version, late_adapter)
    result = gateway.invoke(identity=_identity(), request=_request(spec))

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "ADAPTER_NOT_REGISTERED"
    assert late_adapter.calls == 0


def test_post_construction_schema_registration_cannot_change_validation_language() -> None:
    spec = _spec("reference.snapshot.read")
    registry = CapabilityRegistry([spec])
    adapter = _Adapter()
    adapters = AdapterRegistry()
    adapters.register(spec.adapter.adapter_id, spec.adapter.adapter_version, adapter)
    schemas = ExactSchemaRegistry({spec.output_schema_id: lambda value: None})
    gateway = _gateway(
        registry=registry,
        adapters=adapters,
        schemas=schemas,
        action_permissions={spec.authorization.action: "answer:read"},
    )

    schemas.register(spec.input_schema_id, lambda value: None)
    result = gateway.invoke(identity=_identity(), request=_request(spec))

    assert result.outcome is InvocationOutcome.REJECTED
    assert result.error_code == "INPUT_SCHEMA_INVALID"
    assert adapter.calls == 0
