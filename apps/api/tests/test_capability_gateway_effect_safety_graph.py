from __future__ import annotations

from korpus.application.capability_gateway.adapters import AdapterExecutionResult, AdapterRegistry
from korpus.application.capability_gateway.effect_safety import (
    CompensationMode,
    EffectSafetyDeclaration,
    EffectSafetyRegistry,
    ReconciliationMode,
    effect_safety_graph_errors,
)
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


def _spec(
    capability_id: str,
    *,
    effect: EffectClass = EffectClass.WRITE_REMOTE,
    lifecycle: CapabilityLifecycle = CapabilityLifecycle.ENABLED,
) -> CapabilitySpec:
    effectful = effect in {
        EffectClass.WRITE_REMOTE,
        EffectClass.TRANSACTIONAL_SIDE_EFFECT,
        EffectClass.PRIVILEGED_ADMIN,
    }
    suffix = capability_id.rsplit(".", 1)[-1]
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id=capability_id,
        version="1.0.0",
        description=f"Safety graph test capability {capability_id}.",
        provider_type=ProviderType.CUSTOM,
        adapter=AdapterSpec(adapter_id=f"custom.safety.{suffix}", adapter_version="1.0.0"),
        effect_class=effect,
        input_schema_id=f"urn:korpus:test:safety-graph:{suffix}:input:v1",
        output_schema_id=f"urn:korpus:test:safety-graph:{suffix}:output:v1",
        authorization=AuthorizationSpec(
            action=f"integration:safety:{suffix}",
            resource_mapper="safety_resource_v1",
            requires_explicit_effect_authorization=effectful,
        ),
        evidence=EvidenceSpec(profile=EvidenceProfile.NONE),
        timeouts=TimeoutSpec(total_ms=1000),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=effectful),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.POLICY_GATED,
            max_request_bytes=4096,
            max_response_bytes=4096,
        ),
        lifecycle=lifecycle,
    )


def _irreversible(spec: CapabilitySpec) -> EffectSafetyDeclaration:
    return EffectSafetyDeclaration.for_spec(
        spec,
        compensation_mode=CompensationMode.NONE,
        irreversible=True,
        reconciliation_mode=ReconciliationMode.MANUAL,
        operator_rationale="No rollback exists for this test capability.",
    )


def _compensated(
    spec: CapabilitySpec,
    target: CapabilitySpec,
) -> EffectSafetyDeclaration:
    return EffectSafetyDeclaration.for_spec(
        spec,
        compensation_mode=CompensationMode.COMPENSATING_ACTION,
        irreversible=False,
        reconciliation_mode=ReconciliationMode.PROVIDER_STATUS_QUERY,
        compensation_capability_id=target.capability_id,
        compensation_capability_version=target.version,
        operator_rationale="Exact compensation capability is required by the safety graph.",
    )


def _preflight(
    specs: list[CapabilitySpec],
    safety: EffectSafetyRegistry,
) -> CapabilityDeploymentPreflight:
    adapters = AdapterRegistry()
    validators: dict[str, object] = {}
    action_permissions: dict[str, str] = {}
    for spec in specs:
        adapters.register(spec.adapter.adapter_id, spec.adapter.adapter_version, _Adapter())
        validators[spec.input_schema_id] = lambda value: None
        validators[spec.output_schema_id] = lambda value: None
        action_permissions[spec.authorization.action] = "answer:read"
    schemas = ExactSchemaRegistry(validators)  # type: ignore[arg-type]
    policy = CapabilityPolicyBridge(
        PolicyEngine(),
        action_permissions=action_permissions,
        resource_authorizers={
            "safety_resource_v1": lambda identity, declared, resource: True,
        },
    )
    return CapabilityDeploymentPreflight(
        registry=CapabilityRegistry(specs),
        adapters=adapters,
        schemas=schemas,
        resource_mappers={"safety_resource_v1": object()},
        policy=policy,
        effect_safety=safety,
    )


def test_compensation_target_must_be_registered() -> None:
    primary = _spec("reference.safety.primary")
    absent = _spec("reference.safety.rollback")
    safety = EffectSafetyRegistry([_compensated(primary, absent)])

    errors = effect_safety_graph_errors([primary], safety)

    assert errors == (
        "reference.safety.primary@1.0.0: compensation capability is not registered: "
        "reference.safety.rollback@1.0.0",
    )


def test_compensation_target_must_be_enabled() -> None:
    primary = _spec("reference.safety.primary")
    target = _spec("reference.safety.rollback", lifecycle=CapabilityLifecycle.DISABLED)
    safety = EffectSafetyRegistry([_compensated(primary, target)])

    errors = effect_safety_graph_errors([primary, target], safety)

    assert errors == (
        "reference.safety.primary@1.0.0: compensation capability is not enabled: "
        "reference.safety.rollback@1.0.0 (DISABLED)",
    )


def test_compensation_target_must_be_effectful() -> None:
    primary = _spec("reference.safety.primary")
    target = _spec("reference.safety.rollback", effect=EffectClass.READ_REMOTE)
    safety = EffectSafetyRegistry([_compensated(primary, target)])

    errors = effect_safety_graph_errors([primary, target], safety)

    assert errors == (
        "reference.safety.primary@1.0.0: compensation capability must be effectful: "
        "reference.safety.rollback@1.0.0",
    )


def test_compensation_target_requires_its_own_effect_safety() -> None:
    primary = _spec("reference.safety.primary")
    target = _spec("reference.safety.rollback")
    safety = EffectSafetyRegistry([_compensated(primary, target)])

    errors = effect_safety_graph_errors([primary, target], safety)

    assert errors == (
        "reference.safety.rollback@1.0.0: effect safety declaration is not registered: "
        "reference.safety.rollback@1.0.0",
    )


def test_exact_enabled_effectful_compensation_graph_is_admissible() -> None:
    primary = _spec("reference.safety.primary")
    target = _spec("reference.safety.rollback")
    safety = EffectSafetyRegistry([_compensated(primary, target), _irreversible(target)])

    assert effect_safety_graph_errors([primary, target], safety) == ()


def test_deployment_preflight_rejects_hollow_compensation_plan() -> None:
    primary = _spec("reference.safety.primary")
    absent = _spec("reference.safety.rollback")
    safety = EffectSafetyRegistry([_compensated(primary, absent)])

    errors = _preflight([primary], safety).errors()

    assert any("compensation capability is not registered" in error for error in errors)


def test_deployment_preflight_accepts_exact_compensation_graph() -> None:
    primary = _spec("reference.safety.primary")
    target = _spec("reference.safety.rollback")
    safety = EffectSafetyRegistry([_compensated(primary, target), _irreversible(target)])
    preflight = _preflight([primary, target], safety)

    assert preflight.errors() == ()
    preflight.require_valid()
