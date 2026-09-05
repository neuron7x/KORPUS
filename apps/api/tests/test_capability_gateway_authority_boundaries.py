from __future__ import annotations

from korpus.application.capability_gateway.adapters import AdapterExecutionResult, AdapterRegistry
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.effect_safety import (
    CompensationMode,
    EffectSafetyDeclaration,
    EffectSafetyRegistry,
    ReconciliationMode,
)
from korpus.application.capability_gateway.effects import EffectRecord, EffectReservation, EffectState
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


class _TruthyNonBooleanEffectAuthorizer:
    def authorize(self, **kwargs: object) -> object:
        del kwargs
        return "false"


class _NeverLedger:
    def __init__(self) -> None:
        self.calls = 0

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
        del (
            subject_id,
            idempotency_key,
            binding_digest,
            invocation_id,
            capability_id,
            capability_version,
            logical_resource,
            input_digest,
        )
        self.calls += 1
        raise AssertionError("effect ledger must not be reached without literal authorization")

    def transition(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected: EffectState,
        target: EffectState,
        provider_reference: str | None = None,
    ) -> EffectRecord:
        del subject_id, idempotency_key, expected, target, provider_reference
        self.calls += 1
        raise AssertionError("effect ledger must not transition without literal authorization")


class _Audit:
    def __init__(self) -> None:
        self.calls = 0

    def append(self, **kwargs: object) -> str:
        del kwargs
        self.calls += 1
        return "audit-authority-boundary-1"


class _Adapter:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, **kwargs: object) -> AdapterExecutionResult:
        del kwargs
        self.calls += 1
        return AdapterExecutionResult(output={"unexpected": True})


def _effect_spec() -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.authority.write",
        version="1.0.0",
        description="Effect authorization type-confusion boundary test.",
        provider_type=ProviderType.INTERNAL,
        adapter=AdapterSpec(adapter_id="internal.authority", adapter_version="1.0.0"),
        effect_class=EffectClass.WRITE_REMOTE,
        input_schema_id="urn:korpus:test:authority-input:v1",
        output_schema_id="urn:korpus:test:authority-output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:write",
            resource_mapper="reference_resource_v1",
            requires_explicit_effect_authorization=True,
        ),
        evidence=EvidenceSpec(profile=EvidenceProfile.NONE),
        timeouts=TimeoutSpec(total_ms=100),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=True),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.NONE,
            max_request_bytes=4096,
            max_response_bytes=4096,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _effect_safety(spec: CapabilitySpec) -> EffectSafetyRegistry:
    return EffectSafetyRegistry(
        [
            EffectSafetyDeclaration.for_spec(
                spec,
                compensation_mode=CompensationMode.NONE,
                irreversible=True,
                reconciliation_mode=ReconciliationMode.MANUAL,
                operator_rationale="Test effect is irreversible and requires manual reconciliation.",
            )
        ]
    )


def test_truthy_non_boolean_effect_authorizer_cannot_widen_authority() -> None:
    spec = _effect_spec()
    adapter = _Adapter()
    adapters = AdapterRegistry()
    adapters.register(spec.adapter.adapter_id, spec.adapter.adapter_version, adapter)
    ledger = _NeverLedger()
    audit = _Audit()
    gateway = CapabilityGateway(
        registry=CapabilityRegistry([spec]),
        policy=CapabilityPolicyBridge(
            PolicyEngine(),
            action_permissions={"integration:reference:write": "answer:read"},
            resource_authorizers={
                "reference_resource_v1": lambda identity, declared, resource: True
            },
        ),
        adapters=adapters,
        schemas=_Schemas(),
        resource_mappers={
            "reference_resource_v1": lambda identity, declared, request: "reference:1"
        },
        egress=_Egress(),
        effect_authorizer=_TruthyNonBooleanEffectAuthorizer(),
        effects=ledger,
        audit=audit,
        effect_safety=_effect_safety(spec),
    )
    request = IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id=spec.capability_id,
        capability_version=spec.version,
        input={"reference_id": "1"},
        idempotency_key="idem-authority-1",
    )

    result = gateway.invoke(
        identity=Identity(subject="reader", roles=frozenset({"user"})),
        request=request,
    )

    assert result.outcome is InvocationOutcome.DENIED
    assert result.error_code == "EFFECT_AUTH_REQUIRED"
    assert result.output is None
    assert result.evidence is None
    assert adapter.calls == 0
    assert ledger.calls == 0
    assert audit.calls == 1
