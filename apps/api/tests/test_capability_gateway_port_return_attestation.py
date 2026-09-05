from __future__ import annotations

import pytest

from korpus.application.capability_gateway.egress import CapabilityDataEgressGuard
from korpus.application.capability_gateway.errors import CapabilityPolicyIndeterminate
from korpus.application.capability_gateway.policy import (
    CapabilityPolicyBridge,
    CapabilityPolicyDecision,
)
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
from korpus.domain.models import AccessTier, Identity


class _Classification:
    def classify_request(self, **kwargs: object) -> AccessTier:
        del kwargs
        return AccessTier.PUBLIC


class _TruthyNonBooleanExternalPolicy:
    def permits(self, **kwargs: object) -> object:
        del kwargs
        return "allow"


class _NonNoneCanonicalPolicy:
    def require(self, identity: Identity, permission: str) -> object:
        del identity, permission
        return False


class _PoisonedActionBridge(CapabilityPolicyBridge):
    def __init__(self, mode: str) -> None:
        super().__init__(
            PolicyEngine(),
            action_permissions={"integration:reference:read": "answer:read"},
            resource_authorizers={"reference_resource_v1": lambda identity, spec, resource: True},
        )
        self.mode = mode

    def authorize(self, identity: Identity, spec: CapabilitySpec) -> CapabilityPolicyDecision:
        del identity
        if self.mode == "denied_return":
            return CapabilityPolicyDecision(
                capability_id=spec.capability_id,
                capability_version=spec.version,
                action=spec.authorization.action,
                canonical_permission="answer:read",
                allowed=False,
                reason="poisoned_false_allow",
            )
        return CapabilityPolicyDecision(
            capability_id=spec.capability_id,
            capability_version="9.9.9",
            action=spec.authorization.action,
            canonical_permission="answer:read",
            allowed=True,
            reason="poisoned_wrong_binding",
        )


def _spec() -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.port.attestation",
        version="1.0.0",
        description="Pre-execution port return attestation test capability.",
        provider_type=ProviderType.HTTP,
        adapter=AdapterSpec(adapter_id="http.port-attestation", adapter_version="1.0.0"),
        effect_class=EffectClass.READ_REMOTE,
        input_schema_id="urn:korpus:test:port-attestation-input:v1",
        output_schema_id="urn:korpus:test:port-attestation-output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:read",
            resource_mapper="reference_resource_v1",
        ),
        evidence=EvidenceSpec(profile=EvidenceProfile.NONE),
        timeouts=TimeoutSpec(total_ms=1000),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=False),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.POLICY_GATED,
            max_request_bytes=4096,
            max_response_bytes=4096,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _request() -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.port.attestation",
        capability_version="1.0.0",
        input={"reference_id": "1"},
    )


def _identity() -> Identity:
    return Identity(subject="reader", roles=frozenset({"user"}))


def test_schema_validator_non_none_return_is_not_silent_success() -> None:
    registry = ExactSchemaRegistry(
        {"urn:korpus:test:input:v1": lambda value: False}  # type: ignore[dict-item]
    )

    with pytest.raises(RuntimeError, match="non-None success sentinel"):
        registry.validate("urn:korpus:test:input:v1", {"reference_id": "1"})


def test_external_egress_policy_truthy_non_boolean_cannot_allow_export() -> None:
    guard = CapabilityDataEgressGuard(
        _Classification(),  # type: ignore[arg-type]
        _TruthyNonBooleanExternalPolicy(),  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="non-boolean decision"):
        guard.check(
            identity=_identity(),
            spec=_spec(),
            request=_request(),
            logical_resource="reference:1",
        )


def test_canonical_policy_non_none_require_return_is_indeterminate() -> None:
    bridge = CapabilityPolicyBridge(
        _NonNoneCanonicalPolicy(),  # type: ignore[arg-type]
        action_permissions={"integration:reference:read": "answer:read"},
        resource_authorizers={"reference_resource_v1": lambda identity, spec, resource: True},
    )

    with pytest.raises(CapabilityPolicyIndeterminate, match="non-None authorization sentinel"):
        bridge.authorize(_identity(), _spec())


def test_returned_denial_cannot_be_misread_as_authorized_policy_decision() -> None:
    bridge = _PoisonedActionBridge("denied_return")

    with pytest.raises(CapabilityPolicyIndeterminate, match="not an explicit allow"):
        bridge.authorize_resource(_identity(), _spec(), logical_resource="reference:1")


def test_policy_decision_wrong_capability_version_binding_is_indeterminate() -> None:
    bridge = _PoisonedActionBridge("wrong_binding")

    with pytest.raises(CapabilityPolicyIndeterminate, match="binding mismatch"):
        bridge.authorize_resource(_identity(), _spec(), logical_resource="reference:1")
