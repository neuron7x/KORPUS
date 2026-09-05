from __future__ import annotations

import pytest

from korpus.application.capability_gateway.effect_safety import (
    CompensationMode,
    EffectSafetyDeclaration,
    EffectSafetyRegistry,
    ReconciliationMode,
    effect_safety_graph_errors,
)
from korpus.application.capability_gateway.errors import CapabilityRegistrationError
from korpus.application.capability_gateway.invoke import CapabilityGateway, CapabilityGatewayPorts
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


def _spec(capability_id: str) -> CapabilitySpec:
    suffix = capability_id.rsplit(".", 1)[-1]
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id=capability_id,
        version="1.0.0",
        description=f"Compensation-cycle test capability {capability_id}.",
        provider_type=ProviderType.CUSTOM,
        adapter=AdapterSpec(adapter_id=f"custom.cycle.{suffix}", adapter_version="1.0.0"),
        effect_class=EffectClass.WRITE_REMOTE,
        input_schema_id=f"urn:korpus:test:cycle:{suffix}:input:v1",
        output_schema_id=f"urn:korpus:test:cycle:{suffix}:output:v1",
        authorization=AuthorizationSpec(
            action=f"integration:cycle:{suffix}",
            resource_mapper="cycle_resource_v1",
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


def _compensated(spec: CapabilitySpec, target: CapabilitySpec) -> EffectSafetyDeclaration:
    return EffectSafetyDeclaration.for_spec(
        spec,
        compensation_mode=CompensationMode.COMPENSATING_ACTION,
        irreversible=False,
        reconciliation_mode=ReconciliationMode.PROVIDER_STATUS_QUERY,
        compensation_capability_id=target.capability_id,
        compensation_capability_version=target.version,
        operator_rationale="Compensation edge under graph termination test.",
    )


def _irreversible(spec: CapabilitySpec) -> EffectSafetyDeclaration:
    return EffectSafetyDeclaration.for_spec(
        spec,
        compensation_mode=CompensationMode.NONE,
        irreversible=True,
        reconciliation_mode=ReconciliationMode.MANUAL,
        operator_rationale="Terminal compensation-chain node.",
    )


def _ports(
    specs: list[CapabilitySpec],
    safety: EffectSafetyRegistry,
) -> CapabilityGatewayPorts:
    return CapabilityGatewayPorts(
        registry=CapabilityRegistry(specs),
        policy=object(),  # type: ignore[arg-type]
        adapters=object(),  # type: ignore[arg-type]
        schemas=object(),  # type: ignore[arg-type]
        resource_mappers={},
        egress=object(),  # type: ignore[arg-type]
        effect_authorizer=object(),  # type: ignore[arg-type]
        effects=object(),  # type: ignore[arg-type]
        audit=object(),  # type: ignore[arg-type]
        effect_safety=safety,
    )


def test_two_node_compensation_cycle_is_rejected_deterministically() -> None:
    alpha = _spec("reference.cycle.alpha")
    beta = _spec("reference.cycle.beta")
    safety = EffectSafetyRegistry([
        _compensated(alpha, beta),
        _compensated(beta, alpha),
    ])

    assert effect_safety_graph_errors([beta, alpha], safety) == (
        "compensation cycle detected: reference.cycle.alpha@1.0.0 -> "
        "reference.cycle.beta@1.0.0 -> reference.cycle.alpha@1.0.0",
    )


def test_indirect_three_node_compensation_cycle_is_rejected() -> None:
    alpha = _spec("reference.cycle.alpha")
    beta = _spec("reference.cycle.beta")
    gamma = _spec("reference.cycle.gamma")
    safety = EffectSafetyRegistry([
        _compensated(alpha, beta),
        _compensated(beta, gamma),
        _compensated(gamma, alpha),
    ])

    errors = effect_safety_graph_errors([alpha, beta, gamma], safety)

    assert errors == (
        "compensation cycle detected: reference.cycle.alpha@1.0.0 -> "
        "reference.cycle.beta@1.0.0 -> reference.cycle.gamma@1.0.0 -> "
        "reference.cycle.alpha@1.0.0",
    )


def test_multi_hop_acyclic_compensation_chain_is_admissible() -> None:
    alpha = _spec("reference.cycle.alpha")
    beta = _spec("reference.cycle.beta")
    gamma = _spec("reference.cycle.gamma")
    safety = EffectSafetyRegistry([
        _compensated(alpha, beta),
        _compensated(beta, gamma),
        _irreversible(gamma),
    ])

    assert effect_safety_graph_errors([gamma, alpha, beta], safety) == ()


def test_runtime_composition_rejects_cyclic_recovery_plan() -> None:
    alpha = _spec("reference.cycle.alpha")
    beta = _spec("reference.cycle.beta")
    safety = EffectSafetyRegistry([
        _compensated(alpha, beta),
        _compensated(beta, alpha),
    ])

    with pytest.raises(CapabilityRegistrationError, match="compensation cycle detected"):
        CapabilityGateway(_ports([alpha, beta], safety))
