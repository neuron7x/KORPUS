from __future__ import annotations

from dataclasses import replace

import pytest

from korpus.application.capability_gateway.effect_safety import (
    CompensationMode,
    EffectSafetyDeclaration,
    EffectSafetyRegistry,
    ReconciliationMode,
)
from korpus.application.capability_gateway.effects import (
    EffectRecord,
    EffectState,
    ReconciliationDisposition,
)
from korpus.application.capability_gateway.reconciliation import (
    ReconciliationConflict,
    ReconciliationObservation,
    reconcile_unknown_effect,
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
    ProviderType,
    RetrySpec,
    TimeoutSpec,
)
from korpus.domain.models import Identity

_BINDING = "sha256:" + "1" * 64
_REFERENCE = "provider:transaction:42"


class _Resolver:
    reconciliation_mode = ReconciliationMode.PROVIDER_STATUS_QUERY

    def observe(self, **kwargs: object) -> ReconciliationObservation:
        del kwargs
        return ReconciliationObservation(
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference=_REFERENCE,
        )


class _Ledger:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.reconcile_calls = 0

    def get(self, **kwargs: object) -> EffectRecord:
        del kwargs
        return _record()

    def reconcile(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected_binding_digest: str,
        disposition: ReconciliationDisposition,
        provider_reference: str | None = None,
    ) -> EffectRecord:
        del subject_id, idempotency_key, expected_binding_digest
        self.reconcile_calls += 1
        record = _record()
        if self.mode == "wrong_state":
            return record
        if self.mode == "wrong_binding":
            return replace(
                record,
                subject_id="other-subject",
                state=EffectState.RECONCILED,
                reconciliation_disposition=disposition,
                provider_reference=provider_reference,
            )
        if self.mode == "wrong_disposition":
            return replace(
                record,
                state=EffectState.RECONCILED,
                reconciliation_disposition=ReconciliationDisposition.CONFIRMED_NO_EFFECT,
                provider_reference=provider_reference,
            )
        if self.mode == "wrong_reference":
            return replace(
                record,
                state=EffectState.RECONCILED,
                reconciliation_disposition=disposition,
                provider_reference="provider:wrong",
            )
        return replace(
            record,
            state=EffectState.RECONCILED,
            reconciliation_disposition=disposition,
            provider_reference=provider_reference,
        )


def _spec() -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.reconciliation.attest",
        version="1.0.0",
        description="Reconciliation persistence attestation test capability.",
        provider_type=ProviderType.CUSTOM,
        adapter=AdapterSpec(adapter_id="custom.reconcile-attest", adapter_version="1.0.0"),
        effect_class=EffectClass.WRITE_REMOTE,
        input_schema_id="urn:korpus:test:reconcile-attest-input:v1",
        output_schema_id="urn:korpus:test:reconcile-attest-output:v1",
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


def _safety(spec: CapabilitySpec) -> EffectSafetyRegistry:
    return EffectSafetyRegistry(
        [
            EffectSafetyDeclaration.for_spec(
                spec,
                compensation_mode=CompensationMode.NONE,
                irreversible=True,
                reconciliation_mode=ReconciliationMode.PROVIDER_STATUS_QUERY,
                operator_rationale="Provider status is the exact reconciliation strategy.",
            )
        ]
    )


def _record() -> EffectRecord:
    return EffectRecord(
        subject_id="writer",
        idempotency_key="idem-1",
        binding_digest=_BINDING,
        invocation_id="00000000-0000-0000-0000-000000000001",
        capability_id="reference.reconciliation.attest",
        capability_version="1.0.0",
        logical_resource="reference:1",
        input_digest="sha256:" + "2" * 64,
        state=EffectState.OUTCOME_UNKNOWN,
        provider_reference=_REFERENCE,
    )


def _reconcile(mode: str) -> EffectRecord:
    spec = _spec()
    return reconcile_unknown_effect(
        identity=Identity(subject="writer", roles=frozenset({"admin"})),
        spec=spec,
        idempotency_key="idem-1",
        expected_binding_digest=_BINDING,
        authorized=True,
        ledger=_Ledger(mode),
        resolver=_Resolver(),
        effect_safety=_safety(spec),
    )


@pytest.mark.parametrize(
    "mode",
    ["wrong_state", "wrong_binding", "wrong_disposition", "wrong_reference"],
)
def test_reconciliation_requires_exact_persisted_post_state(mode: str) -> None:
    with pytest.raises(ReconciliationConflict, match="compare-and-set failed"):
        _reconcile(mode)


def test_exact_reconciled_record_is_returned() -> None:
    record = _reconcile("valid")

    assert record.state is EffectState.RECONCILED
    assert record.reconciliation_disposition is ReconciliationDisposition.CONFIRMED_COMMITTED
    assert record.provider_reference == _REFERENCE
