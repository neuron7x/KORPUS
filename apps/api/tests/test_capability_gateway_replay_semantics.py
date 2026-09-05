from __future__ import annotations

import pytest

from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.effects import (
    EffectRecord,
    EffectState,
    ReconciliationDisposition,
)
from korpus.application.capability_gateway.invoke import _replay_semantics
from korpus.infrastructure.capability_observability import CapabilityObservability


def _record(
    state: EffectState,
    disposition: ReconciliationDisposition | None = None,
) -> EffectRecord:
    return EffectRecord(
        subject_id="reader",
        idempotency_key="idem-1",
        binding_digest="sha256:" + "1" * 64,
        invocation_id="00000000-0000-0000-0000-000000000001",
        capability_id="reference.public.write",
        capability_version="1.0.0",
        logical_resource="reference:1",
        input_digest="sha256:" + "2" * 64,
        state=state,
        reconciliation_disposition=disposition,
    )


@pytest.mark.parametrize(
    ("record", "outcome", "error_code"),
    [
        (
            _record(EffectState.PENDING),
            InvocationOutcome.OUTCOME_UNKNOWN,
            "IDEMPOTENT_REPLAY_PENDING",
        ),
        (
            _record(EffectState.OUTCOME_UNKNOWN),
            InvocationOutcome.OUTCOME_UNKNOWN,
            "IDEMPOTENT_REPLAY_REQUIRES_RECONCILIATION",
        ),
        (
            _record(EffectState.COMMITTED),
            InvocationOutcome.FAILED,
            "IDEMPOTENT_REPLAY_COMMITTED",
        ),
        (
            _record(EffectState.FAILED_KNOWN_NO_EFFECT),
            InvocationOutcome.FAILED,
            "IDEMPOTENT_REPLAY_KNOWN_NO_EFFECT",
        ),
        (
            _record(
                EffectState.RECONCILED,
                ReconciliationDisposition.CONFIRMED_COMMITTED,
            ),
            InvocationOutcome.FAILED,
            "IDEMPOTENT_REPLAY_COMMITTED",
        ),
        (
            _record(
                EffectState.RECONCILED,
                ReconciliationDisposition.CONFIRMED_NO_EFFECT,
            ),
            InvocationOutcome.FAILED,
            "IDEMPOTENT_REPLAY_KNOWN_NO_EFFECT",
        ),
    ],
)
def test_replay_semantics_preserve_durable_effect_truth(
    record: EffectRecord,
    outcome: InvocationOutcome,
    error_code: str,
) -> None:
    assert _replay_semantics(record) == (outcome, error_code)


def test_missing_replay_record_fails_closed_instead_of_claiming_reconciliation() -> None:
    assert _replay_semantics(None) == (InvocationOutcome.FAILED, "INTERNAL_ERROR")


def test_only_ambiguous_effect_state_claims_reconciliation_is_required() -> None:
    states = [
        _record(EffectState.PENDING),
        _record(EffectState.OUTCOME_UNKNOWN),
        _record(EffectState.COMMITTED),
        _record(EffectState.FAILED_KNOWN_NO_EFFECT),
        _record(
            EffectState.RECONCILED,
            ReconciliationDisposition.CONFIRMED_COMMITTED,
        ),
        _record(
            EffectState.RECONCILED,
            ReconciliationDisposition.CONFIRMED_NO_EFFECT,
        ),
    ]

    requiring_reconciliation = [
        record.state
        for record in states
        if _replay_semantics(record)[1] == "IDEMPOTENT_REPLAY_REQUIRES_RECONCILIATION"
    ]

    assert requiring_reconciliation == [EffectState.OUTCOME_UNKNOWN]


@pytest.mark.parametrize(
    "error_code",
    [
        "IDEMPOTENT_REPLAY_PENDING",
        "IDEMPOTENT_REPLAY_REQUIRES_RECONCILIATION",
        "IDEMPOTENT_REPLAY_COMMITTED",
        "IDEMPOTENT_REPLAY_KNOWN_NO_EFFECT",
    ],
)
def test_replay_error_codes_remain_bounded_telemetry_vocabulary(error_code: str) -> None:
    assert CapabilityObservability._bounded_error_code(error_code) == error_code
