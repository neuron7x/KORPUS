from __future__ import annotations

import pytest

from korpus.application.capability_gateway.egress import (
    CapabilityDataEgressGuard,
    CapabilityEgressDenied,
)
from korpus.application.capability_gateway.errors import (
    CapabilityContractError,
    CapabilityRegistrationError,
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
from korpus.domain.models import AccessTier, Identity


class _Classifier:
    def __init__(self, tier: AccessTier) -> None:
        self.tier = tier
        self.calls = 0

    def classify_request(self, **kwargs: object) -> AccessTier:
        del kwargs
        self.calls += 1
        return self.tier


class _ExternalPolicy:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.calls = 0

    def permits(self, **kwargs: object) -> bool:
        del kwargs
        self.calls += 1
        return self.allowed


def _spec(
    *,
    provider: ProviderType = ProviderType.HTTP,
    egress: DataEgressClass = DataEgressClass.PUBLIC_ONLY,
) -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.public.read",
        version="1.0.0",
        description="Read governed reference.",
        provider_type=provider,
        adapter=AdapterSpec(adapter_id="http.reference", adapter_version="1.0.0"),
        effect_class=EffectClass.READ_REMOTE,
        input_schema_id="urn:korpus:test:input:v1",
        output_schema_id="urn:korpus:test:output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:read",
            resource_mapper="reference_resource_v1",
        ),
        evidence=EvidenceSpec(profile=EvidenceProfile.NONE),
        timeouts=TimeoutSpec(total_ms=1_000),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=False),
        data_policy=DataPolicySpec(
            egress_class=egress,
            max_request_bytes=16_384,
            max_response_bytes=1_048_576,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _request() -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.public.read",
        capability_version="1.0.0",
        input={"reference_id": "1"},
    )


def test_schema_registry_is_exact_and_immutable() -> None:
    calls: list[object] = []
    registry = ExactSchemaRegistry()
    registry.register("urn:korpus:test:v1", calls.append)

    registry.validate("urn:korpus:test:v1", {"x": 1})

    assert calls == [{"x": 1}]
    with pytest.raises(CapabilityRegistrationError):
        registry.register("urn:korpus:test:v1", calls.append)
    with pytest.raises(CapabilityContractError, match="unknown schema id"):
        registry.validate("urn:korpus:test:v2", {"x": 1})


def test_schema_validator_error_is_normalized_to_contract_failure() -> None:
    def reject(value: object) -> None:
        del value
        raise ValueError("provider-shaped detail must not escape")

    registry = ExactSchemaRegistry({"urn:korpus:test:v1": reject})

    with pytest.raises(CapabilityContractError, match="schema validation failed"):
        registry.validate("urn:korpus:test:v1", {"x": 1})


def test_internal_provider_requires_no_external_data_policy_decision() -> None:
    classifier = _Classifier(AccessTier.RESTRICTED)
    policy = _ExternalPolicy(False)
    guard = CapabilityDataEgressGuard(classifier, policy)

    guard.check(
        identity=Identity(subject="reader", roles=frozenset({"user"})),
        spec=_spec(provider=ProviderType.INTERNAL, egress=DataEgressClass.NONE),
        request=_request(),
        logical_resource="reference:1",
    )

    assert classifier.calls == 0
    assert policy.calls == 0


def test_none_or_restricted_no_egress_denies_remote_before_classification() -> None:
    for egress in (DataEgressClass.NONE, DataEgressClass.RESTRICTED_NO_EGRESS):
        classifier = _Classifier(AccessTier.PUBLIC)
        guard = CapabilityDataEgressGuard(classifier, _ExternalPolicy(True))
        with pytest.raises(CapabilityEgressDenied):
            guard.check(
                identity=Identity(subject="reader", roles=frozenset({"user"})),
                spec=_spec(egress=egress),
                request=_request(),
                logical_resource="reference:1",
            )
        assert classifier.calls == 0


def test_public_only_denies_nonpublic_payload() -> None:
    guard = CapabilityDataEgressGuard(
        _Classifier(AccessTier.AUTHENTICATED),
        _ExternalPolicy(True),
    )

    with pytest.raises(CapabilityEgressDenied, match="PUBLIC_ONLY"):
        guard.check(
            identity=Identity(subject="reader", roles=frozenset({"user"})),
            spec=_spec(egress=DataEgressClass.PUBLIC_ONLY),
            request=_request(),
            logical_resource="reference:1",
        )


def test_policy_gated_requires_deployment_policy_allow() -> None:
    identity = Identity(subject="reader", roles=frozenset({"user"}))
    denied = CapabilityDataEgressGuard(_Classifier(AccessTier.RESTRICTED), _ExternalPolicy(False))
    with pytest.raises(CapabilityEgressDenied, match="deployment"):
        denied.check(
            identity=identity,
            spec=_spec(egress=DataEgressClass.POLICY_GATED),
            request=_request(),
            logical_resource="reference:1",
        )

    allowed = CapabilityDataEgressGuard(_Classifier(AccessTier.RESTRICTED), _ExternalPolicy(True))
    allowed.check(
        identity=identity,
        spec=_spec(egress=DataEgressClass.POLICY_GATED),
        request=_request(),
        logical_resource="reference:1",
    )
