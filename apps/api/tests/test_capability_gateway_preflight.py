from __future__ import annotations

import pytest

from korpus.application.capability_gateway.adapters import AdapterExecutionResult, AdapterRegistry
from korpus.application.capability_gateway.errors import CapabilityRegistrationError
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


class _Adapter:
    def execute(self, **kwargs: object) -> AdapterExecutionResult:
        del kwargs
        return AdapterExecutionResult(output={"ok": True})


def _spec(
    *,
    provider: ProviderType = ProviderType.INTERNAL,
    egress: DataEgressClass = DataEgressClass.NONE,
    effect: EffectClass = EffectClass.READ_LOCAL,
) -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.preflight.read",
        version="1.0.0",
        description="Preflight test capability.",
        provider_type=provider,
        adapter=AdapterSpec(adapter_id="preflight.adapter", adapter_version="1.0.0"),
        effect_class=effect,
        input_schema_id="urn:korpus:test:preflight-input:v1",
        output_schema_id="urn:korpus:test:preflight-output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:read",
            resource_mapper="reference_resource_v1",
        ),
        evidence=EvidenceSpec(profile=EvidenceProfile.NONE),
        timeouts=TimeoutSpec(total_ms=100),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=False),
        data_policy=DataPolicySpec(
            egress_class=egress,
            max_request_bytes=1024,
            max_response_bytes=1024,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _preflight(
    spec: CapabilitySpec,
    *,
    register_adapter: bool = True,
    include_output_schema: bool = True,
    include_mapper: bool = True,
    include_action: bool = True,
    include_resource_authorizer: bool = True,
) -> CapabilityDeploymentPreflight:
    adapters = AdapterRegistry()
    if register_adapter:
        adapters.register("preflight.adapter", "1.0.0", _Adapter())
    validators = {"urn:korpus:test:preflight-input:v1": lambda value: None}
    if include_output_schema:
        validators["urn:korpus:test:preflight-output:v1"] = lambda value: None
    return CapabilityDeploymentPreflight(
        registry=CapabilityRegistry([spec]),
        adapters=adapters,
        schemas=ExactSchemaRegistry(validators),
        resource_mappers={"reference_resource_v1": object()} if include_mapper else {},
        action_permissions={"integration:reference:read": "answer:read"} if include_action else {},
        resource_authorizers=(
            {"reference_resource_v1": object()} if include_resource_authorizer else {}
        ),
    )


def test_complete_enabled_capability_passes_preflight() -> None:
    preflight = _preflight(_spec())

    assert preflight.errors() == ()
    preflight.require_valid()


def test_missing_runtime_dependencies_are_reported_together() -> None:
    preflight = _preflight(
        _spec(),
        register_adapter=False,
        include_output_schema=False,
        include_mapper=False,
        include_action=False,
        include_resource_authorizer=False,
    )

    errors = preflight.errors()
    assert len(errors) == 5
    assert any("output schema is not registered" in error for error in errors)
    assert any("resource mapper is not registered" in error for error in errors)
    assert any("resource authorizer is not registered" in error for error in errors)
    assert any("no canonical permission mapping" in error for error in errors)
    assert any("adapter implementation not registered" in error for error in errors)
    with pytest.raises(CapabilityRegistrationError, match="deployment preflight failed"):
        preflight.require_valid()


def test_missing_resource_authorizer_blocks_otherwise_complete_capability() -> None:
    preflight = _preflight(_spec(), include_resource_authorizer=False)

    assert preflight.errors() == (
        "reference.preflight.read@1.0.0: resource authorizer is not registered: "
        "reference_resource_v1",
    )


def test_enabled_remote_capability_cannot_be_composed_with_no_egress() -> None:
    preflight = _preflight(
        _spec(
            provider=ProviderType.HTTP,
            egress=DataEgressClass.RESTRICTED_NO_EGRESS,
            effect=EffectClass.READ_REMOTE,
        )
    )

    assert any("forbids all egress" in error for error in preflight.errors())


def test_internal_provider_cannot_claim_remote_transport_semantics() -> None:
    preflight = _preflight(
        _spec(
            provider=ProviderType.INTERNAL,
            egress=DataEgressClass.NONE,
            effect=EffectClass.READ_REMOTE,
        )
    )

    assert any("cannot declare a remote effect class" in error for error in preflight.errors())
