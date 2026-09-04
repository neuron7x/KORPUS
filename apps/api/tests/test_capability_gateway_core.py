from __future__ import annotations

import pytest
from pydantic import ValidationError

from korpus.application.capability_gateway.contracts import (
    payload_digest,
    validate_request_binding,
)
from korpus.application.capability_gateway.errors import (
    CapabilityAuthorizationDenied,
    CapabilityContractError,
    CapabilityNotFound,
    CapabilityRegistrationError,
    CapabilityUnavailable,
)
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


def _spec(
    *,
    version: str = "1.0.0",
    lifecycle: CapabilityLifecycle = CapabilityLifecycle.ENABLED,
    idempotency_required: bool = False,
    max_request_bytes: int = 16_384,
) -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.public.read",
        version=version,
        description="Read one governed public reference.",
        provider_type=ProviderType.HTTP,
        adapter=AdapterSpec(adapter_id="http.reference", adapter_version="1.0.0"),
        effect_class=EffectClass.READ_REMOTE,
        input_schema_id="urn:korpus:test:input:v1",
        output_schema_id="urn:korpus:test:output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:read",
            resource_mapper="reference_public_resource_v1",
        ),
        evidence=EvidenceSpec(
            profile=EvidenceProfile.PROVIDER_PROVENANCE,
            freshness_seconds=300,
            bind_output_digest=True,
        ),
        timeouts=TimeoutSpec(total_ms=5_000),
        retry=RetrySpec(max_attempts=2, only_safe_errors=True),
        idempotency=IdempotencySpec(required=idempotency_required),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.PUBLIC_ONLY,
            max_request_bytes=max_request_bytes,
            max_response_bytes=1_048_576,
        ),
        lifecycle=lifecycle,
    )


def _request(*, version: str = "1.0.0", idempotency_key: str | None = None) -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.public.read",
        capability_version=version,
        input={"reference_id": "abc"},
        idempotency_key=idempotency_key,
    )


def test_capability_spec_rejects_untrusted_extra_authority_fields() -> None:
    payload = _spec().model_dump(mode="json")
    payload["trusted"] = True
    with pytest.raises(ValidationError):
        CapabilitySpec.model_validate(payload)


def test_registry_resolves_only_exact_enabled_version() -> None:
    registry = CapabilityRegistry([_spec(version="1.0.0"), _spec(version="2.0.0")])

    assert registry.resolve_exact("reference.public.read", "1.0.0").version == "1.0.0"
    assert registry.resolve_exact("reference.public.read", "2.0.0").version == "2.0.0"

    with pytest.raises(CapabilityNotFound):
        registry.resolve_exact("reference.public.read", "3.0.0")


def test_registry_refuses_non_enabled_capability() -> None:
    registry = CapabilityRegistry([_spec(lifecycle=CapabilityLifecycle.VALIDATED)])

    with pytest.raises(CapabilityUnavailable):
        registry.resolve_exact("reference.public.read", "1.0.0")


def test_registry_refuses_duplicate_exact_identity() -> None:
    registry = CapabilityRegistry([_spec()])

    with pytest.raises(CapabilityRegistrationError):
        registry.register(_spec())


def test_policy_bridge_denies_unmapped_capability_action() -> None:
    bridge = CapabilityPolicyBridge(PolicyEngine(), action_permissions={})
    identity = Identity(subject="reader", roles=frozenset({"user"}))

    with pytest.raises(CapabilityAuthorizationDenied, match="unmapped capability action"):
        bridge.authorize(identity, _spec())


def test_policy_bridge_rejects_noncanonical_permission_mapping_at_composition() -> None:
    with pytest.raises(ValueError, match="unknown canonical permission"):
        CapabilityPolicyBridge(
            PolicyEngine(),
            action_permissions={"integration:reference:read": "integration:reference:read"},
        )


def test_policy_bridge_delegates_allow_to_canonical_policy_engine() -> None:
    bridge = CapabilityPolicyBridge(
        PolicyEngine(),
        action_permissions={"integration:reference:read": "answer:read"},
    )
    identity = Identity(subject="reader", roles=frozenset({"user"}))

    decision = bridge.authorize(identity, _spec())

    assert decision.allowed is True
    assert decision.canonical_permission == "answer:read"
    assert decision.reason == "canonical_policy_allowed"


def test_policy_bridge_delegates_deny_to_canonical_policy_engine() -> None:
    bridge = CapabilityPolicyBridge(
        PolicyEngine(),
        action_permissions={"integration:reference:read": "audit:verify"},
    )
    identity = Identity(subject="reader", roles=frozenset({"user"}))

    with pytest.raises(CapabilityAuthorizationDenied, match="canonical policy denied"):
        bridge.authorize(identity, _spec())


def test_request_binding_refuses_version_mismatch_without_fallback() -> None:
    with pytest.raises(CapabilityContractError, match="does not match resolved spec"):
        validate_request_binding(_request(version="2.0.0"), _spec(version="1.0.0"))


def test_request_binding_requires_idempotency_when_declared() -> None:
    with pytest.raises(CapabilityContractError, match="idempotency key is required"):
        validate_request_binding(_request(), _spec(idempotency_required=True))


def test_request_binding_enforces_canonical_utf8_byte_budget() -> None:
    request = IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.public.read",
        capability_version="1.0.0",
        input={"value": "абв"},
    )
    spec = _spec(max_request_bytes=5)

    with pytest.raises(CapabilityContractError, match="exceeds capability maximum"):
        validate_request_binding(request, spec)


def test_payload_digest_is_order_independent_for_json_object_keys() -> None:
    assert payload_digest({"b": 2, "a": 1}) == payload_digest({"a": 1, "b": 2})
