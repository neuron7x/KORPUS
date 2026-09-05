from __future__ import annotations

import pytest
from pydantic import ValidationError

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


def _payload() -> dict[str, object]:
    return {
        "schema_version": "korpus.capability-spec.v1",
        "capability_id": "reference.effect.write",
        "version": "1.0.0",
        "description": "Effect contract under test.",
        "provider_type": ProviderType.CUSTOM,
        "adapter": AdapterSpec(adapter_id="custom.effect", adapter_version="1.0.0"),
        "effect_class": EffectClass.WRITE_REMOTE,
        "input_schema_id": "urn:korpus:test:effect-input:v1",
        "output_schema_id": "urn:korpus:test:effect-output:v1",
        "authorization": AuthorizationSpec(
            action="integration:effect:write",
            resource_mapper="effect_resource_v1",
            requires_explicit_effect_authorization=True,
        ),
        "evidence": EvidenceSpec(profile=EvidenceProfile.SIGNED_RECEIPT, bind_output_digest=True),
        "timeouts": TimeoutSpec(total_ms=1000),
        "retry": RetrySpec(max_attempts=1),
        "idempotency": IdempotencySpec(required=True, provider_key_forwarding=True),
        "data_policy": DataPolicySpec(
            egress_class=DataEgressClass.POLICY_GATED,
            max_request_bytes=4096,
            max_response_bytes=4096,
        ),
        "lifecycle": CapabilityLifecycle.ENABLED,
    }


def test_effectful_capability_requires_durable_idempotency_at_registration_time() -> None:
    payload = _payload()
    payload["idempotency"] = IdempotencySpec(required=False)

    with pytest.raises(ValidationError, match="must require durable idempotency"):
        CapabilitySpec.model_validate(payload)


def test_effectful_capability_requires_explicit_effect_authorization_declaration() -> None:
    payload = _payload()
    payload["authorization"] = AuthorizationSpec(
        action="integration:effect:write",
        resource_mapper="effect_resource_v1",
        requires_explicit_effect_authorization=False,
    )

    with pytest.raises(ValidationError, match="must require explicit effect authorization"):
        CapabilitySpec.model_validate(payload)


def test_read_capability_cannot_claim_explicit_effect_authorization() -> None:
    payload = _payload()
    payload["effect_class"] = EffectClass.READ_REMOTE
    payload["idempotency"] = IdempotencySpec(required=False)

    with pytest.raises(ValidationError, match="valid only for effectful"):
        CapabilitySpec.model_validate(payload)


def test_provider_key_forwarding_requires_a_local_idempotency_identity() -> None:
    payload = _payload()
    payload["effect_class"] = EffectClass.READ_REMOTE
    payload["authorization"] = AuthorizationSpec(
        action="integration:effect:read",
        resource_mapper="effect_resource_v1",
    )
    payload["idempotency"] = IdempotencySpec(required=False, provider_key_forwarding=True)

    with pytest.raises(ValidationError, match="forwarding requires idempotency"):
        CapabilitySpec.model_validate(payload)


def test_multiple_attempts_require_safe_error_classification() -> None:
    payload = _payload()
    payload["retry"] = RetrySpec(max_attempts=2, only_safe_errors=False)

    with pytest.raises(ValidationError, match="only_safe_errors=true"):
        CapabilitySpec.model_validate(payload)


def test_effectful_multiple_attempts_require_provider_duplicate_prevention_proof() -> None:
    payload = _payload()
    payload["retry"] = RetrySpec(max_attempts=2, only_safe_errors=True)
    payload["idempotency"] = IdempotencySpec(required=True, provider_key_forwarding=False)

    with pytest.raises(ValidationError, match="provider idempotency-key forwarding proof"):
        CapabilitySpec.model_validate(payload)


def test_effectful_multiple_attempts_are_admissible_with_provider_key_forwarding() -> None:
    payload = _payload()
    payload["retry"] = RetrySpec(max_attempts=2, only_safe_errors=True)

    spec = CapabilitySpec.model_validate(payload)

    assert spec.retry.max_attempts == 2
    assert spec.retry.only_safe_errors is True
    assert spec.idempotency.provider_key_forwarding is True


def test_declared_evidence_profile_cannot_disable_output_digest_binding() -> None:
    payload = _payload()
    payload["evidence"] = EvidenceSpec(
        profile=EvidenceProfile.SIGNED_RECEIPT,
        bind_output_digest=False,
    )

    with pytest.raises(ValidationError, match="must bind the exact output digest"):
        CapabilitySpec.model_validate(payload)


def test_declared_evidence_profile_defaults_to_output_digest_binding() -> None:
    evidence = EvidenceSpec(profile=EvidenceProfile.FACTUAL_EVIDENCE)

    assert evidence.bind_output_digest is True


def test_valid_effect_contract_remains_admissible() -> None:
    spec = CapabilitySpec.model_validate(_payload())

    assert spec.effect_class is EffectClass.WRITE_REMOTE
    assert spec.idempotency.required is True
    assert spec.authorization.requires_explicit_effect_authorization is True
