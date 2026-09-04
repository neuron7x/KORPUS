from __future__ import annotations

import pytest
from pydantic import ValidationError

from korpus.application.capability_gateway.adapters import AdapterExecutionResult, AdapterRegistry
from korpus.application.capability_gateway.effect_safety import (
    CompensationMode,
    EffectSafetyDeclaration,
    EffectSafetyRegistry,
    ReconciliationMode,
)
from korpus.application.capability_gateway.errors import CapabilityRegistrationError
from korpus.application.capability_gateway.invoke import CapabilityGateway, CapabilityGatewayPorts
from korpus.application.capability_gateway.policy import CapabilityPolicyBridge
from korpus.application.capability_gateway.preflight import CapabilityDeploymentPreflight
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
    ProviderType,
    RetrySpec,
    TimeoutSpec,
)
from korpus.application.capability_gateway.validation import ExactSchemaRegistry
from korpus.application.policy import PolicyEngine


class _Adapter:
    def execute(self, **kwargs: object) -> AdapterExecutionResult:
        del kwargs
        return AdapterExecutionResult(output={"ok": True})


def _effect_spec() -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.safety.write",
        version="1.0.0",
        description="Effect safety declaration test capability.",
        provider_type=ProviderType.CUSTOM,
        adapter=AdapterSpec(adapter_id="custom.safety", adapter_version="1.0.0"),
        effect_class=EffectClass.WRITE_REMOTE,
        input_schema_id="urn:korpus:test:safety-input:v1",
        output_schema_id="urn:korpus:test:safety-output:v1",
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


def _manual_irreversible(spec: CapabilitySpec) -> EffectSafetyDeclaration:
    return EffectSafetyDeclaration.for_spec(
        spec,
        compensation_mode=CompensationMode.NONE,
        irreversible=True,
        reconciliation_mode=ReconciliationMode.MANUAL,
        operator_rationale="No provider rollback exists; ambiguous outcomes require manual reconciliation.",
    )


def _adapters_and_schemas(spec: CapabilitySpec) -> tuple[AdapterRegistry, ExactSchemaRegistry]:
    adapters = AdapterRegistry()
    adapters.register(spec.adapter.adapter_id, spec.adapter.adapter_version, _Adapter())
    schemas = ExactSchemaRegistry(
        {
            spec.input_schema_id: lambda value: None,
            spec.output_schema_id: lambda value: None,
        }
    )
    return adapters, schemas


def _policy(spec: CapabilitySpec) -> CapabilityPolicyBridge:
    return CapabilityPolicyBridge(
        PolicyEngine(),
        action_permissions={spec.authorization.action: "answer:read"},
        resource_authorizers={
            spec.authorization.resource_mapper: lambda identity, declared, resource: True
        },
    )


def _preflight(
    spec: CapabilitySpec,
    safety: EffectSafetyRegistry | None = None,
) -> CapabilityDeploymentPreflight:
    adapters, schemas = _adapters_and_schemas(spec)
    return CapabilityDeploymentPreflight(
        registry=CapabilityRegistry([spec]),
        adapters=adapters,
        schemas=schemas,
        resource_mappers={spec.authorization.resource_mapper: object()},
        policy=_policy(spec),
        effect_safety=safety,
    )


def _structured_ports(
    spec: CapabilitySpec,
    safety: EffectSafetyRegistry | None,
) -> CapabilityGatewayPorts:
    adapters, schemas = _adapters_and_schemas(spec)
    return CapabilityGatewayPorts(
        registry=CapabilityRegistry([spec]),
        policy=_policy(spec),
        adapters=adapters,
        schemas=schemas,
        resource_mappers={
            spec.authorization.resource_mapper: lambda identity, declared, request: "reference:1"
        },
        egress=object(),  # type: ignore[arg-type]
        effect_authorizer=object(),  # type: ignore[arg-type]
        effects=object(),  # type: ignore[arg-type]
        audit=object(),  # type: ignore[arg-type]
        effect_safety=safety,
    )


def test_no_compensation_requires_explicit_irreversibility() -> None:
    with pytest.raises(ValidationError, match="explicitly irreversible"):
        EffectSafetyDeclaration.for_spec(
            _effect_spec(),
            compensation_mode=CompensationMode.NONE,
            irreversible=False,
            reconciliation_mode=ReconciliationMode.MANUAL,
            operator_rationale="Invalid declaration under test.",
        )


def test_compensating_action_requires_exact_distinct_capability_identity() -> None:
    spec = _effect_spec()
    with pytest.raises(ValidationError, match="exact compensation capability"):
        EffectSafetyDeclaration.for_spec(
            spec,
            compensation_mode=CompensationMode.COMPENSATING_ACTION,
            irreversible=False,
            reconciliation_mode=ReconciliationMode.PROVIDER_STATUS_QUERY,
            operator_rationale="Missing exact compensation identity under test.",
        )

    with pytest.raises(ValidationError, match="cannot self-reference"):
        EffectSafetyDeclaration.for_spec(
            spec,
            compensation_mode=CompensationMode.COMPENSATING_ACTION,
            irreversible=False,
            reconciliation_mode=ReconciliationMode.PROVIDER_STATUS_QUERY,
            operator_rationale="Self-reference is not a compensation plan.",
            compensation_capability_id=spec.capability_id,
            compensation_capability_version=spec.version,
        )


def test_same_version_capability_drift_invalidates_safety_declaration() -> None:
    original = _effect_spec()
    registry = EffectSafetyRegistry([_manual_irreversible(original)])
    drifted = original.model_copy(update={"description": "Same version, changed local contract."})

    registry.resolve_exact(original)
    with pytest.raises(CapabilityRegistrationError, match="contract drift"):
        registry.resolve_exact(drifted)


def test_effectful_preflight_fails_closed_without_safety_declaration() -> None:
    preflight = _preflight(_effect_spec())

    errors = preflight.errors()
    assert len(errors) == 1
    assert "effect safety declaration is not registered" in errors[0]
    with pytest.raises(CapabilityRegistrationError, match="deployment preflight failed"):
        preflight.require_valid()


def test_exact_bound_effect_safety_allows_preflight_without_granting_authority() -> None:
    spec = _effect_spec()
    safety = EffectSafetyRegistry([_manual_irreversible(spec)])
    preflight = _preflight(spec, safety)

    assert preflight.errors() == ()
    preflight.require_valid()
    declaration = safety.resolve_exact(spec)
    assert declaration.irreversible is True
    assert declaration.compensation_mode is CompensationMode.NONE
    assert declaration.reconciliation_mode is ReconciliationMode.MANUAL


def test_structured_effectful_gateway_composition_rejects_missing_safety() -> None:
    with pytest.raises(CapabilityRegistrationError, match="effectful gateway composition rejected"):
        CapabilityGateway(_structured_ports(_effect_spec(), None))


def test_structured_effectful_gateway_composition_accepts_exact_safety_only() -> None:
    spec = _effect_spec()
    safety = EffectSafetyRegistry([_manual_irreversible(spec)])

    gateway = CapabilityGateway(_structured_ports(spec, safety))

    assert isinstance(gateway, CapabilityGateway)
