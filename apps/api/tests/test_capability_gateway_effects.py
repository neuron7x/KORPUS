from __future__ import annotations

from dataclasses import replace

import pytest

from korpus.application.capability_gateway.effects import (
    EffectAuthorizationRequired,
    EffectRecord,
    EffectReservation,
    EffectState,
    IdempotencyConflict,
    InvalidEffectTransition,
    assert_effect_transition,
    prepare_effect_guard,
)
from korpus.application.capability_gateway.errors import CapabilityContractError
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


class _MemoryLedger:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], EffectRecord] = {}

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
        key = subject_id, idempotency_key
        existing = self.records.get(key)
        if existing is not None:
            return EffectReservation(record=existing, created=False)
        record = EffectRecord(
            subject_id=subject_id,
            idempotency_key=idempotency_key,
            binding_digest=binding_digest,
            invocation_id=invocation_id,
            capability_id=capability_id,
            capability_version=capability_version,
            logical_resource=logical_resource,
            input_digest=input_digest,
            state=EffectState.PENDING,
        )
        self.records[key] = record
        return EffectReservation(record=record, created=True)

    def transition(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected: EffectState,
        target: EffectState,
        provider_reference: str | None = None,
    ) -> EffectRecord:
        key = subject_id, idempotency_key
        current = self.records[key]
        if current.state is not expected:
            raise RuntimeError("compare-and-set failed")
        assert_effect_transition(current.state, target)
        updated = replace(current, state=target, provider_reference=provider_reference)
        self.records[key] = updated
        return updated


def _spec(
    *,
    idempotency_required: bool = True,
    explicit_effect_authorization: bool = True,
) -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.public.write",
        version="1.0.0",
        description="Write one governed public reference.",
        provider_type=ProviderType.HTTP,
        adapter=AdapterSpec(adapter_id="http.reference", adapter_version="1.0.0"),
        effect_class=EffectClass.WRITE_REMOTE,
        input_schema_id="urn:korpus:test:write-input:v1",
        output_schema_id="urn:korpus:test:write-output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:write",
            resource_mapper="reference_public_resource_v1",
            requires_explicit_effect_authorization=explicit_effect_authorization,
        ),
        evidence=EvidenceSpec(profile=EvidenceProfile.SIGNED_RECEIPT, bind_output_digest=True),
        timeouts=TimeoutSpec(total_ms=5_000),
        retry=RetrySpec(max_attempts=1, only_safe_errors=True),
        idempotency=IdempotencySpec(required=idempotency_required, provider_key_forwarding=True),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.PUBLIC_ONLY,
            max_request_bytes=16_384,
            max_response_bytes=1_048_576,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _request(*, key: str | None = "idem-1", value: str = "x") -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.public.write",
        capability_version="1.0.0",
        input={"value": value},
        idempotency_key=key,
    )


def test_effect_guard_requires_durable_idempotency_declaration() -> None:
    with pytest.raises(CapabilityContractError, match="durable idempotency"):
        prepare_effect_guard(
            identity=Identity(subject="writer", roles=frozenset({"admin"})),
            spec=_spec(idempotency_required=False),
            request=_request(),
            logical_resource="reference:1",
            invocation_id="inv-1",
            ledger=_MemoryLedger(),
            explicit_effect_authorized=True,
        )


def test_effect_guard_requires_separate_trusted_effect_authorization() -> None:
    with pytest.raises(EffectAuthorizationRequired):
        prepare_effect_guard(
            identity=Identity(subject="writer", roles=frozenset({"admin"})),
            spec=_spec(),
            request=_request(),
            logical_resource="reference:1",
            invocation_id="inv-1",
            ledger=_MemoryLedger(),
            explicit_effect_authorized=False,
        )


def test_same_idempotency_binding_replays_without_duplicate_execution() -> None:
    ledger = _MemoryLedger()
    kwargs = {
        "identity": Identity(subject="writer", roles=frozenset({"admin"})),
        "spec": _spec(),
        "request": _request(),
        "logical_resource": "reference:1",
        "ledger": ledger,
        "explicit_effect_authorized": True,
    }

    first = prepare_effect_guard(invocation_id="inv-1", **kwargs)
    second = prepare_effect_guard(invocation_id="inv-2", **kwargs)

    assert first.should_execute is True
    assert second.should_execute is False
    assert second.binding_digest == first.binding_digest


def test_same_idempotency_key_with_different_binding_is_conflict_within_subject() -> None:
    ledger = _MemoryLedger()
    identity = Identity(subject="writer", roles=frozenset({"admin"}))
    spec = _spec()
    prepare_effect_guard(
        identity=identity,
        spec=spec,
        request=_request(value="first"),
        logical_resource="reference:1",
        invocation_id="inv-1",
        ledger=ledger,
        explicit_effect_authorized=True,
    )

    with pytest.raises(IdempotencyConflict):
        prepare_effect_guard(
            identity=identity,
            spec=spec,
            request=_request(value="second"),
            logical_resource="reference:1",
            invocation_id="inv-2",
            ledger=ledger,
            explicit_effect_authorized=True,
        )


def test_same_client_key_is_isolated_between_subjects() -> None:
    ledger = _MemoryLedger()
    first = prepare_effect_guard(
        identity=Identity(subject="writer-a", roles=frozenset({"admin"})),
        spec=_spec(),
        request=_request(),
        logical_resource="reference:1",
        invocation_id="inv-1",
        ledger=ledger,
        explicit_effect_authorized=True,
    )
    second = prepare_effect_guard(
        identity=Identity(subject="writer-b", roles=frozenset({"admin"})),
        spec=_spec(),
        request=_request(),
        logical_resource="reference:1",
        invocation_id="inv-2",
        ledger=ledger,
        explicit_effect_authorized=True,
    )

    assert first.should_execute is True
    assert second.should_execute is True
    assert len(ledger.records) == 2


def test_effect_state_machine_allows_unknown_only_from_pending() -> None:
    assert_effect_transition(EffectState.PENDING, EffectState.OUTCOME_UNKNOWN)

    with pytest.raises(InvalidEffectTransition):
        assert_effect_transition(EffectState.COMMITTED, EffectState.OUTCOME_UNKNOWN)


def test_outcome_unknown_can_only_reconcile_once() -> None:
    assert_effect_transition(EffectState.OUTCOME_UNKNOWN, EffectState.RECONCILED)

    with pytest.raises(InvalidEffectTransition):
        assert_effect_transition(EffectState.RECONCILED, EffectState.COMMITTED)
