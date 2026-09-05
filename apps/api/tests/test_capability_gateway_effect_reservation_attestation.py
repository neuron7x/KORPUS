from __future__ import annotations

import pytest

from korpus.application.capability_gateway.contracts import payload_digest
from korpus.application.capability_gateway.effects import (
    EffectRecord,
    EffectReservation,
    EffectState,
    InvalidEffectReservation,
    effect_binding_digest,
    prepare_effect_guard,
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
from korpus.domain.models import Identity

_LOGICAL_RESOURCE = "reference:1"
_INVOCATION_ID = "00000000-0000-0000-0000-000000000001"


class _Ledger:
    def __init__(self, reservation: object) -> None:
        self.reservation = reservation
        self.calls = 0

    def reserve(self, **kwargs: object) -> EffectReservation:
        del kwargs
        self.calls += 1
        return self.reservation  # type: ignore[return-value]

    def transition(self, **kwargs: object) -> EffectRecord:
        del kwargs
        raise AssertionError("transition is outside reservation attestation")


def _spec() -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.attestation.write",
        version="1.0.0",
        description="Effect reservation attestation test capability.",
        provider_type=ProviderType.CUSTOM,
        adapter=AdapterSpec(adapter_id="custom.attestation", adapter_version="1.0.0"),
        effect_class=EffectClass.WRITE_REMOTE,
        input_schema_id="urn:korpus:test:attestation-input:v1",
        output_schema_id="urn:korpus:test:attestation-output:v1",
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


def _identity() -> Identity:
    return Identity(subject="writer", roles=frozenset({"user"}))


def _request() -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.attestation.write",
        capability_version="1.0.0",
        input={"reference_id": "1"},
        idempotency_key="idem-1",
    )


def _record(*, state: EffectState, invocation_id: str = _INVOCATION_ID) -> EffectRecord:
    identity = _identity()
    spec = _spec()
    request = _request()
    return EffectRecord(
        subject_id=identity.subject,
        idempotency_key="idem-1",
        binding_digest=effect_binding_digest(
            identity=identity,
            spec=spec,
            request=request,
            logical_resource=_LOGICAL_RESOURCE,
        ),
        invocation_id=invocation_id,
        capability_id=spec.capability_id,
        capability_version=spec.version,
        logical_resource=_LOGICAL_RESOURCE,
        input_digest=payload_digest(request.input),
        state=state,
    )


def _guard(ledger: _Ledger):
    return prepare_effect_guard(
        identity=_identity(),
        spec=_spec(),
        request=_request(),
        logical_resource=_LOGICAL_RESOURCE,
        invocation_id=_INVOCATION_ID,
        ledger=ledger,
        explicit_effect_authorized=True,
    )


def test_new_reservation_cannot_claim_already_committed_state() -> None:
    ledger = _Ledger(EffectReservation(record=_record(state=EffectState.COMMITTED), created=True))

    with pytest.raises(InvalidEffectReservation, match="new effect reservation is not PENDING"):
        _guard(ledger)

    assert ledger.calls == 1


def test_new_reservation_must_bind_current_invocation_exactly() -> None:
    ledger = _Ledger(
        EffectReservation(
            record=_record(
                state=EffectState.PENDING,
                invocation_id="00000000-0000-0000-0000-000000000099",
            ),
            created=True,
        )
    )

    with pytest.raises(InvalidEffectReservation, match="invocation binding is inconsistent"):
        _guard(ledger)


def test_same_digest_cannot_mask_mismatched_durable_identity_fields() -> None:
    record = _record(state=EffectState.COMMITTED)
    poisoned = EffectRecord(
        subject_id="other-subject",
        idempotency_key=record.idempotency_key,
        binding_digest=record.binding_digest,
        invocation_id=record.invocation_id,
        capability_id=record.capability_id,
        capability_version=record.capability_version,
        logical_resource=record.logical_resource,
        input_digest=record.input_digest,
        state=record.state,
    )
    ledger = _Ledger(EffectReservation(record=poisoned, created=False))

    with pytest.raises(InvalidEffectReservation, match="exact binding fields are inconsistent"):
        _guard(ledger)


def test_valid_existing_committed_reservation_never_redispatches() -> None:
    ledger = _Ledger(EffectReservation(record=_record(state=EffectState.COMMITTED), created=False))

    guard = _guard(ledger)

    assert guard.required is True
    assert guard.should_execute is False
    assert guard.reservation is not None
    assert guard.reservation.record.state is EffectState.COMMITTED


def test_invalid_reservation_runtime_type_is_rejected() -> None:
    ledger = _Ledger({"created": True, "state": "PENDING"})

    with pytest.raises(InvalidEffectReservation, match="invalid reservation type"):
        _guard(ledger)
