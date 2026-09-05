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
from korpus.application.capability_gateway.errors import CapabilityAuthorizationDenied
from korpus.application.capability_gateway.reconciliation import (
    ReconciliationConflict,
    ReconciliationIndeterminate,
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


def _spec(*, version: str = "1.0.0", description: str | None = None) -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.reconcile.write",
        version=version,
        description=description or "Reconciliation semantics test capability.",
        provider_type=ProviderType.CUSTOM,
        adapter=AdapterSpec(adapter_id="custom.reconcile", adapter_version="1.0.0"),
        effect_class=EffectClass.WRITE_REMOTE,
        input_schema_id="urn:korpus:test:reconcile-input:v1",
        output_schema_id="urn:korpus:test:reconcile-output:v1",
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


def _safety(
    spec: CapabilitySpec,
    *,
    mode: ReconciliationMode = ReconciliationMode.PROVIDER_STATUS_QUERY,
) -> EffectSafetyRegistry:
    return EffectSafetyRegistry(
        [
            EffectSafetyDeclaration.for_spec(
                spec,
                compensation_mode=CompensationMode.NONE,
                irreversible=True,
                reconciliation_mode=mode,
                operator_rationale="Test effect is irreversible; reconciliation mode is exact-bound.",
            )
        ]
    )


def _record(*, provider_reference: str | None = "provider:transaction:42") -> EffectRecord:
    return EffectRecord(
        subject_id="writer",
        idempotency_key="idem-1",
        binding_digest="sha256:" + "1" * 64,
        invocation_id="00000000-0000-0000-0000-000000000001",
        capability_id="reference.reconcile.write",
        capability_version="1.0.0",
        logical_resource="reference:1",
        input_digest="sha256:" + "2" * 64,
        state=EffectState.OUTCOME_UNKNOWN,
        provider_reference=provider_reference,
    )


class _Ledger:
    def __init__(self, record: EffectRecord | None = None) -> None:
        self.record = record
        self.reconcile_calls = 0

    def get(self, *, subject_id: str, idempotency_key: str) -> EffectRecord | None:
        if self.record is None:
            return None
        if (subject_id, idempotency_key) != (
            self.record.subject_id,
            self.record.idempotency_key,
        ):
            return None
        return self.record

    def reconcile(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected_binding_digest: str,
        disposition: ReconciliationDisposition,
        provider_reference: str | None = None,
    ) -> EffectRecord:
        self.reconcile_calls += 1
        if self.record is None:
            raise RuntimeError("missing")
        if (subject_id, idempotency_key) != (
            self.record.subject_id,
            self.record.idempotency_key,
        ):
            raise RuntimeError("identity mismatch")
        if self.record.binding_digest != expected_binding_digest:
            raise RuntimeError("binding mismatch")
        if self.record.state is not EffectState.OUTCOME_UNKNOWN:
            raise RuntimeError("state mismatch")
        self.record = replace(
            self.record,
            state=EffectState.RECONCILED,
            provider_reference=provider_reference,
            reconciliation_disposition=disposition,
        )
        return self.record


class _Resolver:
    def __init__(
        self,
        observation: ReconciliationObservation | None = None,
        error: Exception | None = None,
        *,
        mode: ReconciliationMode = ReconciliationMode.PROVIDER_STATUS_QUERY,
    ) -> None:
        self.reconciliation_mode = mode
        self.observation = observation or ReconciliationObservation(
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference="provider:transaction:42",
        )
        self.error = error
        self.calls = 0

    def observe(self, **kwargs: object) -> ReconciliationObservation:
        del kwargs
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.observation


def _reconcile(
    *,
    ledger: _Ledger,
    resolver: _Resolver,
    authorized: bool = True,
    spec: CapabilitySpec | None = None,
    binding: str = "sha256:" + "1" * 64,
    safety: EffectSafetyRegistry | None = None,
) -> EffectRecord:
    selected_spec = spec or _spec()
    return reconcile_unknown_effect(
        identity=Identity(subject="writer", roles=frozenset({"admin"})),
        spec=selected_spec,
        idempotency_key="idem-1",
        expected_binding_digest=binding,
        authorized=authorized,
        ledger=ledger,
        resolver=resolver,
        effect_safety=safety or _safety(selected_spec),
    )


def test_reconciliation_requires_literal_authorization_before_provider_observation() -> None:
    ledger = _Ledger(_record())
    resolver = _Resolver()

    with pytest.raises(CapabilityAuthorizationDenied):
        _reconcile(ledger=ledger, resolver=resolver, authorized=False)

    assert resolver.calls == 0
    assert ledger.reconcile_calls == 0
    assert ledger.record is not None
    assert ledger.record.state is EffectState.OUTCOME_UNKNOWN


def test_wrong_exact_binding_blocks_provider_observation() -> None:
    ledger = _Ledger(_record())
    resolver = _Resolver()

    with pytest.raises(ReconciliationConflict, match="idempotency binding mismatch"):
        _reconcile(
            ledger=ledger,
            resolver=resolver,
            binding="sha256:" + "9" * 64,
        )

    assert resolver.calls == 0
    assert ledger.reconcile_calls == 0


def test_wrong_capability_version_blocks_provider_observation() -> None:
    ledger = _Ledger(_record())
    resolver = _Resolver()

    with pytest.raises(ReconciliationConflict, match="capability binding mismatch"):
        _reconcile(ledger=ledger, resolver=resolver, spec=_spec(version="2.0.0"))

    assert resolver.calls == 0
    assert ledger.reconcile_calls == 0


def test_missing_effect_safety_blocks_provider_observation() -> None:
    ledger = _Ledger(_record())
    resolver = _Resolver()

    with pytest.raises(ReconciliationConflict, match="effect safety declaration"):
        _reconcile(
            ledger=ledger,
            resolver=resolver,
            safety=EffectSafetyRegistry(),
        )

    assert resolver.calls == 0
    assert ledger.reconcile_calls == 0
    assert ledger.record is not None
    assert ledger.record.state is EffectState.OUTCOME_UNKNOWN


def test_same_version_safety_drift_blocks_provider_observation() -> None:
    original = _spec()
    drifted = _spec(description="Same identity, drifted contract under reconciliation test.")
    ledger = _Ledger(_record())
    resolver = _Resolver()

    with pytest.raises(ReconciliationConflict, match="effect safety declaration"):
        _reconcile(
            ledger=ledger,
            resolver=resolver,
            spec=drifted,
            safety=_safety(original),
        )

    assert resolver.calls == 0
    assert ledger.reconcile_calls == 0


def test_manual_reconciliation_mode_never_invokes_automatic_provider_resolver() -> None:
    spec = _spec()
    ledger = _Ledger(_record())
    resolver = _Resolver()

    with pytest.raises(ReconciliationIndeterminate, match="manual reconciliation"):
        _reconcile(
            ledger=ledger,
            resolver=resolver,
            spec=spec,
            safety=_safety(spec, mode=ReconciliationMode.MANUAL),
        )

    assert resolver.calls == 0
    assert ledger.reconcile_calls == 0
    assert ledger.record is not None
    assert ledger.record.state is EffectState.OUTCOME_UNKNOWN


def test_resolver_mode_mismatch_blocks_provider_observation() -> None:
    spec = _spec()
    ledger = _Ledger(_record())
    resolver = _Resolver(mode=ReconciliationMode.PROVIDER_IDEMPOTENCY_LOOKUP)

    with pytest.raises(ReconciliationConflict, match="resolver mode does not match"):
        _reconcile(
            ledger=ledger,
            resolver=resolver,
            spec=spec,
            safety=_safety(spec, mode=ReconciliationMode.PROVIDER_STATUS_QUERY),
        )

    assert resolver.calls == 0
    assert ledger.reconcile_calls == 0


def test_provider_resolver_failure_preserves_ambiguity() -> None:
    ledger = _Ledger(_record())
    resolver = _Resolver(error=OSError("provider status unavailable"))

    with pytest.raises(ReconciliationIndeterminate, match="could not decide"):
        _reconcile(ledger=ledger, resolver=resolver)

    assert resolver.calls == 1
    assert ledger.reconcile_calls == 0
    assert ledger.record is not None
    assert ledger.record.state is EffectState.OUTCOME_UNKNOWN


def test_provider_reference_drift_cannot_reconcile_wrong_effect() -> None:
    ledger = _Ledger(_record(provider_reference="provider:transaction:42"))
    resolver = _Resolver(
        ReconciliationObservation(
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference="provider:transaction:attacker",
        )
    )

    with pytest.raises(ReconciliationConflict, match="provider reference changed"):
        _reconcile(ledger=ledger, resolver=resolver)

    assert resolver.calls == 1
    assert ledger.reconcile_calls == 0


@pytest.mark.parametrize(
    "mode",
    [
        ReconciliationMode.PROVIDER_STATUS_QUERY,
        ReconciliationMode.PROVIDER_IDEMPOTENCY_LOOKUP,
    ],
)
@pytest.mark.parametrize(
    "disposition",
    [
        ReconciliationDisposition.CONFIRMED_COMMITTED,
        ReconciliationDisposition.CONFIRMED_NO_EFFECT,
    ],
)
def test_successful_reconciliation_records_exact_terminal_disposition(
    mode: ReconciliationMode,
    disposition: ReconciliationDisposition,
) -> None:
    spec = _spec()
    ledger = _Ledger(_record())
    resolver = _Resolver(
        ReconciliationObservation(
            disposition=disposition,
            provider_reference="provider:transaction:42",
        ),
        mode=mode,
    )

    result = _reconcile(
        ledger=ledger,
        resolver=resolver,
        spec=spec,
        safety=_safety(spec, mode=mode),
    )

    assert result.state is EffectState.RECONCILED
    assert result.reconciliation_disposition is disposition
    assert result.provider_reference == "provider:transaction:42"
    assert resolver.calls == 1
    assert ledger.reconcile_calls == 1


def test_reconciled_record_cannot_be_reconciled_twice() -> None:
    record = replace(
        _record(),
        state=EffectState.RECONCILED,
        reconciliation_disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
    )
    ledger = _Ledger(record)
    resolver = _Resolver()

    with pytest.raises(ReconciliationConflict, match="not reconcilable"):
        _reconcile(ledger=ledger, resolver=resolver)

    assert resolver.calls == 0
    assert ledger.reconcile_calls == 0


def test_effect_record_cannot_encode_empty_or_misplaced_reconciliation_disposition() -> None:
    with pytest.raises(ValueError, match="requires a resolved disposition"):
        replace(_record(), state=EffectState.RECONCILED)

    with pytest.raises(ValueError, match="valid only for RECONCILED"):
        replace(
            _record(),
            reconciliation_disposition=ReconciliationDisposition.CONFIRMED_NO_EFFECT,
        )
