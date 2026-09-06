from __future__ import annotations

from dataclasses import replace

from korpus.application.capability_gateway.adapters import AdapterRegistry
from korpus.application.capability_gateway.effects import (
    EffectGuard,
    EffectRecord,
    EffectReservation,
    EffectState,
)
from korpus.application.capability_gateway.execution import CapabilityExecutor
from korpus.application.capability_gateway.result import CapabilityResultEmitter


class _Schemas:
    def validate(self, schema_id: str, value: object) -> None:
        del schema_id, value


class _Audit:
    def append(self, **kwargs: object) -> str:
        del kwargs
        return "audit-transition-attestation"


class _Effects:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.calls = 0

    def transition(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected: EffectState,
        target: EffectState,
        provider_reference: str | None = None,
    ) -> EffectRecord:
        del subject_id, idempotency_key
        self.calls += 1
        assert expected is EffectState.PENDING
        if self.mode == "invalid_type":
            return {"state": target.value}  # type: ignore[return-value]
        record = _record()
        if self.mode == "wrong_state":
            return record
        if self.mode == "wrong_binding":
            return replace(
                record,
                subject_id="other-subject",
                state=target,
                provider_reference=provider_reference,
            )
        if self.mode == "wrong_provider_reference":
            return replace(record, state=target, provider_reference="provider:wrong")
        return replace(record, state=target, provider_reference=provider_reference)


def _record() -> EffectRecord:
    return EffectRecord(
        subject_id="writer",
        idempotency_key="idem-1",
        binding_digest="sha256:" + "1" * 64,
        invocation_id="00000000-0000-0000-0000-000000000001",
        capability_id="reference.transition.write",
        capability_version="1.0.0",
        logical_resource="reference:1",
        input_digest="sha256:" + "2" * 64,
        state=EffectState.PENDING,
    )


def _guard() -> EffectGuard:
    record = _record()
    return EffectGuard(
        required=True,
        should_execute=True,
        binding_digest=record.binding_digest,
        reservation=EffectReservation(record=record, created=True),
    )


def _executor(effects: _Effects) -> CapabilityExecutor:
    return CapabilityExecutor(
        adapters=AdapterRegistry(),
        schemas=_Schemas(),
        effects=effects,  # type: ignore[arg-type]
        emitter=CapabilityResultEmitter(_Audit()),  # type: ignore[arg-type]
    )


def test_transition_success_requires_requested_state_to_be_observed() -> None:
    effects = _Effects("wrong_state")

    assert _executor(effects)._transition(_guard(), EffectState.COMMITTED) is False
    assert effects.calls == 1


def test_transition_success_requires_immutable_binding_to_survive() -> None:
    effects = _Effects("wrong_binding")

    assert _executor(effects)._transition(_guard(), EffectState.COMMITTED) is False


def test_transition_success_requires_provider_reference_to_match() -> None:
    effects = _Effects("wrong_provider_reference")

    assert (
        _executor(effects)._transition(
            _guard(),
            EffectState.OUTCOME_UNKNOWN,
            provider_reference="provider:expected",
        )
        is False
    )


def test_invalid_transition_runtime_type_is_not_treated_as_persisted() -> None:
    effects = _Effects("invalid_type")

    assert _executor(effects)._transition(_guard(), EffectState.COMMITTED) is False


def test_exact_transition_record_is_accepted() -> None:
    effects = _Effects("valid")

    assert (
        _executor(effects)._transition(
            _guard(),
            EffectState.COMMITTED,
            provider_reference="provider:receipt:1",
        )
        is True
    )
