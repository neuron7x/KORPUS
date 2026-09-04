from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from korpus.application.capability_gateway.effects import EffectState
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
