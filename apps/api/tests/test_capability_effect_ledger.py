from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from korpus.application.capability_gateway.effects import (
    EffectState,
    InvalidEffectTransition,
    ReconciliationDisposition,
)
from korpus.infrastructure.capability_effect_ledger import (
    EffectLedgerConflict,
    SqlEffectLedger,
    capability_effect_metadata,
)


def _reserve(ledger: SqlEffectLedger, *, subject: str = "writer", key: str = "idem-1") -> bool:
    return ledger.reserve(
        subject_id=subject,
        idempotency_key=key,
        binding_digest="sha256:" + "1" * 64,
        invocation_id="00000000-0000-0000-0000-000000000001",
        capability_id="reference.public.write",
        capability_version="1.0.0",
        logical_resource="reference:1",
        input_digest="sha256:" + "2" * 64,
    ).created


def _engine(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'effects.sqlite'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    capability_effect_metadata.create_all(engine)
    return engine


def _mark_unknown(
    ledger: SqlEffectLedger,
    *,
    provider_reference: str | None = "provider:transaction:42",
) -> None:
    _reserve(ledger)
    ledger.transition(
        subject_id="writer",
        idempotency_key="idem-1",
        expected=EffectState.PENDING,
        target=EffectState.OUTCOME_UNKNOWN,
        provider_reference=provider_reference,
    )


def test_sql_effect_ledger_is_durable_across_instances(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    first = SqlEffectLedger(engine)
    second = SqlEffectLedger(engine)

    assert _reserve(first) is True
    assert _reserve(second) is False
    record = second.get(subject_id="writer", idempotency_key="idem-1")

    assert record is not None
    assert record.capability_id == "reference.public.write"
    assert record.state is EffectState.PENDING
    assert record.reconciliation_disposition is None


def test_sql_effect_ledger_scopes_client_key_by_subject(tmp_path: Path) -> None:
    ledger = SqlEffectLedger(_engine(tmp_path))

    assert _reserve(ledger, subject="writer-a") is True
    assert _reserve(ledger, subject="writer-b") is True


def test_sql_effect_ledger_compare_and_set_transition(tmp_path: Path) -> None:
    ledger = SqlEffectLedger(_engine(tmp_path))
    _reserve(ledger)

    committed = ledger.transition(
        subject_id="writer",
        idempotency_key="idem-1",
        expected=EffectState.PENDING,
        target=EffectState.COMMITTED,
        provider_reference="provider:receipt:1",
    )

    assert committed.state is EffectState.COMMITTED
    assert committed.provider_reference == "provider:receipt:1"
    with pytest.raises(EffectLedgerConflict):
        ledger.transition(
            subject_id="writer",
            idempotency_key="idem-1",
            expected=EffectState.PENDING,
            target=EffectState.OUTCOME_UNKNOWN,
        )


def test_concurrent_same_subject_reservation_has_single_winner(tmp_path: Path) -> None:
    ledger = SqlEffectLedger(_engine(tmp_path))

    with ThreadPoolExecutor(max_workers=8) as pool:
        created = list(pool.map(lambda _: _reserve(ledger), range(16)))

    assert created.count(True) == 1
    assert created.count(False) == 15


def test_generic_transition_cannot_create_semantically_empty_reconciled_state(
    tmp_path: Path,
) -> None:
    ledger = SqlEffectLedger(_engine(tmp_path))
    _mark_unknown(ledger)

    with pytest.raises(InvalidEffectTransition, match="explicit disposition"):
        ledger.transition(
            subject_id="writer",
            idempotency_key="idem-1",
            expected=EffectState.OUTCOME_UNKNOWN,
            target=EffectState.RECONCILED,
        )


@pytest.mark.parametrize(
    "disposition",
    [
        ReconciliationDisposition.CONFIRMED_COMMITTED,
        ReconciliationDisposition.CONFIRMED_NO_EFFECT,
    ],
)
def test_reconciliation_persists_explicit_terminal_disposition(
    tmp_path: Path,
    disposition: ReconciliationDisposition,
) -> None:
    ledger = SqlEffectLedger(_engine(tmp_path))
    _mark_unknown(ledger)

    reconciled = ledger.reconcile(
        subject_id="writer",
        idempotency_key="idem-1",
        expected_binding_digest="sha256:" + "1" * 64,
        disposition=disposition,
        provider_reference="provider:transaction:42",
    )

    assert reconciled.state is EffectState.RECONCILED
    assert reconciled.reconciliation_disposition is disposition
    assert reconciled.provider_reference == "provider:transaction:42"


def test_reconciliation_binding_mismatch_leaves_unknown_state_unchanged(tmp_path: Path) -> None:
    ledger = SqlEffectLedger(_engine(tmp_path))
    _mark_unknown(ledger)

    with pytest.raises(EffectLedgerConflict, match="binding mismatch"):
        ledger.reconcile(
            subject_id="writer",
            idempotency_key="idem-1",
            expected_binding_digest="sha256:" + "9" * 64,
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference="provider:transaction:42",
        )

    current = ledger.get(subject_id="writer", idempotency_key="idem-1")
    assert current is not None
    assert current.state is EffectState.OUTCOME_UNKNOWN
    assert current.reconciliation_disposition is None


def test_reconciliation_provider_reference_cannot_silently_change(tmp_path: Path) -> None:
    ledger = SqlEffectLedger(_engine(tmp_path))
    _mark_unknown(ledger, provider_reference="provider:transaction:42")

    with pytest.raises(EffectLedgerConflict, match="provider reference changed"):
        ledger.reconcile(
            subject_id="writer",
            idempotency_key="idem-1",
            expected_binding_digest="sha256:" + "1" * 64,
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference="provider:transaction:attacker",
        )

    current = ledger.get(subject_id="writer", idempotency_key="idem-1")
    assert current is not None
    assert current.state is EffectState.OUTCOME_UNKNOWN


def test_concurrent_reconciliation_has_exactly_one_terminal_winner(tmp_path: Path) -> None:
    ledger = SqlEffectLedger(_engine(tmp_path))
    _mark_unknown(ledger)

    dispositions = [
        ReconciliationDisposition.CONFIRMED_COMMITTED,
        ReconciliationDisposition.CONFIRMED_NO_EFFECT,
    ]

    def attempt(disposition: ReconciliationDisposition) -> ReconciliationDisposition | None:
        try:
            record = ledger.reconcile(
                subject_id="writer",
                idempotency_key="idem-1",
                expected_binding_digest="sha256:" + "1" * 64,
                disposition=disposition,
                provider_reference="provider:transaction:42",
            )
        except EffectLedgerConflict:
            return None
        return record.reconciliation_disposition

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, dispositions))

    assert sum(result is not None for result in results) == 1
    current = ledger.get(subject_id="writer", idempotency_key="idem-1")
    assert current is not None
    assert current.state is EffectState.RECONCILED
    assert current.reconciliation_disposition in dispositions
