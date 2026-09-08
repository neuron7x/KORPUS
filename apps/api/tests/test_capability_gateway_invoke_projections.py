"""Проєкція повтору й композиція портів — межі, які не можна пройти двічі по-різному.

`_replay_semantics` перекладає ДУРАБЛЬНИЙ стан у вирок повтору, не вигадуючи
неоднозначності: читання з тим самим ключем не може означати, що зовнішня зміна
відбулась. `_normalize_ports` не дає зібрати шлюз із двох суперечливих оголошень
портів. Виміряно 08.09.2026: сім непокритих гілок, і всі — саме ці межі.
"""

from __future__ import annotations

import pytest
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.effects import (
    EffectRecord,
    EffectState,
    ReconciliationDisposition,
)
from korpus.application.capability_gateway.invoke import _normalize_ports, _replay_semantics

BINDING = "sha256:" + "1" * 64


def _record(**overrides: object) -> EffectRecord:
    fields: dict[str, object] = {
        "subject_id": "writer",
        "idempotency_key": "idem-1",
        "binding_digest": BINDING,
        "invocation_id": "00000000-0000-0000-0000-000000000001",
        "capability_id": "reference.public.write",
        "capability_version": "1.0.0",
        "logical_resource": "reference:1",
        "input_digest": "sha256:" + "2" * 64,
        "state": EffectState.PENDING,
    }
    fields.update(overrides)
    return EffectRecord(**fields)  # type: ignore[arg-type]


def _reconciled(disposition: ReconciliationDisposition) -> EffectRecord:
    return _record(state=EffectState.RECONCILED, reconciliation_disposition=disposition)


def test_a_reconciled_commitment_replays_as_committed() -> None:
    outcome, code = _replay_semantics(
        _reconciled(ReconciliationDisposition.CONFIRMED_COMMITTED), effectful_operation=True
    )
    assert (outcome, code) == (InvocationOutcome.FAILED, "IDEMPOTENT_REPLAY_COMMITTED")


def test_a_reconciled_absence_of_effect_replays_as_known_no_effect() -> None:
    """«Підтверджено, що дії не було» — це знання, а не невдача узгодження."""
    outcome, code = _replay_semantics(
        _reconciled(ReconciliationDisposition.CONFIRMED_NO_EFFECT), effectful_operation=True
    )
    assert (outcome, code) == (InvocationOutcome.FAILED, "IDEMPOTENT_REPLAY_KNOWN_NO_EFFECT")


def test_a_reconciled_record_on_a_read_is_an_internal_error() -> None:
    """Читання не буває узгодженим: узгодження існує лише для ефектної неоднозначності."""
    outcome, code = _replay_semantics(
        _reconciled(ReconciliationDisposition.CONFIRMED_COMMITTED), effectful_operation=False
    )
    assert (outcome, code) == (InvocationOutcome.FAILED, "INTERNAL_ERROR")


def test_an_unknown_outcome_on_a_read_is_an_internal_error() -> None:
    """Збій транспорту читання не може означати, що зовнішня зміна відбулась."""
    outcome, code = _replay_semantics(
        _record(state=EffectState.OUTCOME_UNKNOWN), effectful_operation=False
    )
    assert (outcome, code) == (InvocationOutcome.FAILED, "INTERNAL_ERROR")


def test_no_record_at_all_is_an_internal_error() -> None:
    assert _replay_semantics(None) == (InvocationOutcome.FAILED, "INTERNAL_ERROR")


def test_both_port_styles_at_once_are_refused() -> None:
    """Два оголошення портів — два шлюзи; який із них діє, було б невидимо."""
    with pytest.raises(TypeError, match="not both"):
        _normalize_ports(object(), {"registry": object()})  # type: ignore[arg-type]


def test_an_incomplete_legacy_port_set_is_refused() -> None:
    with pytest.raises(TypeError, match="missing="):
        _normalize_ports(None, {"registry": object()})


def test_an_unknown_legacy_port_key_is_refused() -> None:
    """Зайвий порт мовчки ігнорувався б, і композиція казала б не те, що робить."""
    from korpus.application.capability_gateway.invoke import (
        _LEGACY_OPTIONAL_PORT_KEYS,
        _LEGACY_REQUIRED_PORT_KEYS,
    )

    legacy = {key: object() for key in _LEGACY_REQUIRED_PORT_KEYS | _LEGACY_OPTIONAL_PORT_KEYS}
    legacy["not_a_port"] = object()
    with pytest.raises(TypeError, match="extra="):
        _normalize_ports(None, legacy)
