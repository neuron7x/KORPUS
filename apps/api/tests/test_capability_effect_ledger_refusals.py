"""Відмови реєстру побічних дій — кожна окремим входом.

Реєстр існує щоб керована побічна дія не сталась двічі: резервація ідемпотентності
переживає перезапуск і конкурентні репліки, а перехід стану — порівняння-і-запис.
Виміряно 08.09.2026: 13 непокритих гілок, і всі вони — конфлікти й перевірки входу,
тобто саме те, заради чого реєстр і є.

Фікстури беруться з `test_capability_effect_ledger`: друга копія розійшлася б мовчки.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from korpus.application.capability_gateway.effects import (
    EffectState,
    ReconciliationDisposition,
)
from korpus.infrastructure.capability_effect_ledger import (
    EffectLedgerConflict,
    SqlEffectLedger,
)

from apps.api.tests.test_capability_effect_ledger import _engine, _mark_unknown, _reserve

DIGEST = "sha256:" + "1" * 64


def _ledger(tmp_path: Path) -> SqlEffectLedger:
    return SqlEffectLedger(engine=_engine(tmp_path))


@pytest.mark.parametrize(
    "disposition",
    ["CONFIRMED_COMMITTED", 7, None],
)
def test_a_disposition_that_is_not_a_registered_enum_is_refused(
    tmp_path: Path, disposition: object
) -> None:
    """Рядок, схожий на розпорядження, розпорядженням не є.

    Інакше друкарська помилка в назві стану пройшла б як термінальний стан, і
    неоднозначність була б стерта семантично порожнім «RECONCILED».
    """
    ledger = _ledger(tmp_path)
    _mark_unknown(ledger)
    with pytest.raises(ValueError):
        ledger.reconcile(
            subject_id="writer",
            idempotency_key="idem-1",
            expected_binding_digest=DIGEST,
            disposition=disposition,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("reference", ["", "   ", 7, "x" * 513])
def test_a_provider_reference_that_is_not_a_bounded_string_is_refused(
    tmp_path: Path, reference: object
) -> None:
    ledger = _ledger(tmp_path)
    _mark_unknown(ledger)
    with pytest.raises(ValueError):
        ledger.reconcile(
            subject_id="writer",
            idempotency_key="idem-1",
            expected_binding_digest=DIGEST,
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference=reference,  # type: ignore[arg-type]
        )


def test_reconciling_a_reservation_that_does_not_exist_is_a_conflict(tmp_path: Path) -> None:
    """Немає резервації — немає чого узгоджувати; це конфлікт, а не тихий успіх."""
    ledger = _ledger(tmp_path)
    with pytest.raises(EffectLedgerConflict):
        ledger.reconcile(
            subject_id="writer",
            idempotency_key="never-reserved",
            expected_binding_digest=DIGEST,
            disposition=ReconciliationDisposition.CONFIRMED_NO_EFFECT,
        )


def test_transitioning_a_reservation_that_does_not_exist_is_a_conflict(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    with pytest.raises(EffectLedgerConflict):
        ledger.transition(
            subject_id="writer",
            idempotency_key="never-reserved",
            expected=EffectState.PENDING,
            target=EffectState.COMMITTED,
        )


def test_reconciling_a_reservation_not_in_unknown_state_is_a_conflict(tmp_path: Path) -> None:
    """Узгодження визначає НЕВИЗНАЧЕНЕ. Визначений стан ним не переписується."""
    ledger = _ledger(tmp_path)
    _reserve(ledger)
    ledger.transition(
        subject_id="writer",
        idempotency_key="idem-1",
        expected=EffectState.PENDING,
        target=EffectState.COMMITTED,
    )
    with pytest.raises(EffectLedgerConflict):
        ledger.reconcile(
            subject_id="writer",
            idempotency_key="idem-1",
            expected_binding_digest=DIGEST,
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
        )


def test_a_reservation_taken_twice_returns_the_first_one(tmp_path: Path) -> None:
    """Друга резервація тим самим ключем не створює другої дії — вона повертає першу."""
    ledger = _ledger(tmp_path)
    assert _reserve(ledger) is True
    assert _reserve(ledger) is False


def test_postgres_binder_absence_is_a_runtime_refusal(tmp_path: Path) -> None:
    """RLS без прив'язки суб'єкта — порожній контекст, а не «менша безпека».

    Конструктор цього стану не пускає; перевірка в рантаймі стоїть на випадок
    підміни поля чи десеріалізації, і саме тому вона мусить бути прогнана.
    """
    ledger = _ledger(tmp_path)
    object.__setattr__(ledger, "_bind_subject", None)
    with ledger.engine.connect() as connection:
        ledger._bind(connection, "writer")  # sqlite: прив'язки немає й не треба

    class _Postgres:
        name = "postgresql"

    object.__setattr__(ledger.engine, "dialect", _Postgres())
    with ledger.engine.connect() as connection, pytest.raises(RuntimeError):
        ledger._bind(connection, "writer")
