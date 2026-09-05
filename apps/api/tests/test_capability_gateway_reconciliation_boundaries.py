from __future__ import annotations

import pytest

from korpus.application.capability_gateway.effect_safety import ReconciliationMode
from korpus.application.capability_gateway.effects import EffectRecord, EffectState, ReconciliationDisposition
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

_BINDING = "sha256:" + "1" * 64


def _spec() -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.reconcile.boundary",
        version="1.0.0",
        description="Boundary normalization reconciliation capability.",
        provider_type=ProviderType.CUSTOM,
        adapter=AdapterSpec(adapter_id="custom.reconcile-boundary", adapter_version="1.0.0"),
        effect_class=EffectClass.WRITE_REMOTE,
        input_schema_id="urn:korpus:test:reconcile-boundary-input:v1",
        output_schema_id="urn:korpus:test:reconcile-boundary-output:v1",
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


def _record() -> EffectRecord:
    return EffectRecord(
        subject_id="writer",
        idempotency_key="idem-1",
        binding_digest=_BINDING,
        invocation_id="00000000-0000-0000-0000-000000000001",
        capability_id="reference.reconcile.boundary",
        capability_version="1.0.0",
        logical_resource="reference:1",
        input_digest="sha256:" + "2" * 64,
        state=EffectState.OUTCOME_UNKNOWN,
        provider_reference="provider:transaction:42",
    )


class _Ledger:
    def __init__(self, *, get_error: Exception | None = None) -> None:
        self.get_error = get_error
        self.get_calls = 0
        self.reconcile_calls = 0

    def get(self, *, subject_id: str, idempotency_key: str) -> EffectRecord | None:
        del subject_id, idempotency_key
        self.get_calls += 1
        if self.get_error is not None:
            raise self.get_error
        return _record()

    def reconcile(self, **kwargs: object) -> EffectRecord:
        del kwargs
        self.reconcile_calls += 1
        raise AssertionError("reconciliation persistence must not run in this negative control")


class _Safety:
    reconciliation_mode = ReconciliationMode.PROVIDER_STATUS_QUERY


class _SafetyRegistry:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def resolve_exact(self, spec: CapabilitySpec) -> _Safety:
        del spec
        self.calls += 1
        if self.error is not None:
            raise self.error
        return _Safety()


class _Resolver:
    reconciliation_mode = ReconciliationMode.PROVIDER_STATUS_QUERY

    def __init__(self) -> None:
        self.calls = 0

    def observe(self, **kwargs: object) -> ReconciliationObservation:
        del kwargs
        self.calls += 1
        return ReconciliationObservation(
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference="provider:transaction:42",
        )


class _ExplodingModeResolver:
    def __init__(self) -> None:
        self.observe_calls = 0

    @property
    def reconciliation_mode(self) -> ReconciliationMode:
        raise RuntimeError("composition property exploded")

    def observe(self, **kwargs: object) -> ReconciliationObservation:
        del kwargs
        self.observe_calls += 1
        raise AssertionError("provider observation must not run when resolver mode is unavailable")


def _invoke(*, ledger: object, resolver: object, safety: object) -> EffectRecord:
    return reconcile_unknown_effect(
        identity=Identity(subject="writer", roles=frozenset({"admin"})),
        spec=_spec(),
        idempotency_key="idem-1",
        expected_binding_digest=_BINDING,
        authorized=True,
        ledger=ledger,  # type: ignore[arg-type]
        resolver=resolver,  # type: ignore[arg-type]
        effect_safety=safety,  # type: ignore[arg-type]
    )


def test_durable_state_read_failure_is_indeterminate_before_provider_observation() -> None:
    ledger = _Ledger(get_error=OSError("database unavailable"))
    resolver = _Resolver()
    safety = _SafetyRegistry()

    with pytest.raises(ReconciliationIndeterminate, match="durable reconciliation state"):
        _invoke(ledger=ledger, resolver=resolver, safety=safety)

    assert ledger.get_calls == 1
    assert ledger.reconcile_calls == 0
    assert safety.calls == 0
    assert resolver.calls == 0


def test_unexpected_effect_safety_failure_is_stable_conflict_before_provider_observation() -> None:
    ledger = _Ledger()
    resolver = _Resolver()
    safety = _SafetyRegistry(error=OSError("safety registry corrupted"))

    with pytest.raises(ReconciliationConflict, match="could not be evaluated"):
        _invoke(ledger=ledger, resolver=resolver, safety=safety)

    assert ledger.get_calls == 1
    assert ledger.reconcile_calls == 0
    assert safety.calls == 1
    assert resolver.calls == 0


def test_resolver_mode_accessor_failure_is_stable_conflict_without_observation() -> None:
    ledger = _Ledger()
    resolver = _ExplodingModeResolver()
    safety = _SafetyRegistry()

    with pytest.raises(ReconciliationConflict, match="resolver mode could not be evaluated"):
        _invoke(ledger=ledger, resolver=resolver, safety=safety)

    assert ledger.get_calls == 1
    assert ledger.reconcile_calls == 0
    assert safety.calls == 1
    assert resolver.observe_calls == 0
