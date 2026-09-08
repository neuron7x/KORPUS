"""Те, що ПОВЕРНУВ впорскуваний реєстр, не є істиною через свою анотацію типу.

`attest_effect_transition` і `_attest_reservation` існують саме тому, що реєстр —
порт: його реалізацію дає композиційний корінь, а тести підміняють. Значення, яке
статично оголошене як `EffectRecord`, у рантаймі може бути будь-чим, і саме на цьому
шляху одна побічна дія стає двома. Виміряно 08.09.2026: вісім непокритих гілок, і всі
вони — ці перевірки.

Кожен тест рухає РІВНО ОДНЕ поле: інакше зелений вирок не каже, яка перевірка його дала.
"""

from __future__ import annotations

import pytest
from korpus.application.capability_gateway.effects import (
    EffectRecord,
    EffectReservation,
    EffectState,
    InvalidEffectTransition,
    ReconciliationDisposition,
    attest_effect_transition,
)

BINDING = "sha256:" + "1" * 64
INVOCATION = "00000000-0000-0000-0000-000000000001"


def _record(**overrides: object) -> EffectRecord:
    fields: dict[str, object] = {
        "subject_id": "writer",
        "idempotency_key": "idem-1",
        "binding_digest": BINDING,
        "invocation_id": INVOCATION,
        "capability_id": "reference.public.write",
        "capability_version": "1.0.0",
        "logical_resource": "reference:1",
        "input_digest": "sha256:" + "2" * 64,
        "state": EffectState.PENDING,
    }
    fields.update(overrides)
    return EffectRecord(**fields)  # type: ignore[arg-type]


def test_a_transition_result_that_is_not_a_record_is_refused() -> None:
    """Порт може повернути що завгодно; анотація типу цього не боронить."""
    with pytest.raises(InvalidEffectTransition, match="invalid transition record type"):
        attest_effect_transition(_record(), {"state": "COMMITTED"}, target=EffectState.COMMITTED)


def test_a_transition_that_changed_immutable_binding_is_refused() -> None:
    """Перехід міняє СТАН, не предмет. Інакше резервація вказувала б на іншу дію."""
    updated = _record(state=EffectState.COMMITTED, logical_resource="reference:99")
    with pytest.raises(InvalidEffectTransition, match="immutable reservation binding"):
        attest_effect_transition(_record(), updated, target=EffectState.COMMITTED)


def test_a_transition_that_did_not_persist_the_requested_state_is_refused() -> None:
    updated = _record(state=EffectState.PENDING)
    with pytest.raises(InvalidEffectTransition, match="did not persist"):
        attest_effect_transition(_record(), updated, target=EffectState.COMMITTED)


def test_a_transition_whose_provider_reference_differs_is_refused() -> None:
    """Посилання провайдера — частина запису дії, а не вільне поле реєстру."""
    updated = _record(state=EffectState.COMMITTED, provider_reference="provider:other")
    with pytest.raises(InvalidEffectTransition, match="provider reference does not match"):
        attest_effect_transition(
            _record(), updated, target=EffectState.COMMITTED, provider_reference="provider:42"
        )


def test_an_ordinary_transition_cannot_set_a_reconciliation_disposition() -> None:
    """Розпорядження узгодження ставить лише узгодження.

    Інакше звичайний перехід міг би оголосити невизначений наслідок визначеним, не
    спитавши провайдера — тобто стерти неоднозначність замість того, щоб її вирішити.
    """
    # Конструктор `EffectRecord` цього стану не пускає — саме тому перевірка нижче є
    # захистом на випадок запису, зробленого ПОВЗ конструктор: десеріалізації, підміни
    # поля, чужої реалізації порту. Відтворюється саме він.
    updated = _record(state=EffectState.COMMITTED)
    object.__setattr__(
        updated, "reconciliation_disposition", ReconciliationDisposition.CONFIRMED_COMMITTED
    )
    with pytest.raises(InvalidEffectTransition, match="reconciliation disposition"):
        attest_effect_transition(_record(), updated, target=EffectState.COMMITTED)


def test_a_faithful_transition_is_accepted() -> None:
    """Негативний контроль: перевірки карають РОЗБІЖНІСТЬ, а не сам перехід."""
    updated = _record(state=EffectState.COMMITTED, provider_reference="provider:42")
    assert (
        attest_effect_transition(
            _record(), updated, target=EffectState.COMMITTED, provider_reference="provider:42"
        )
        is updated
    )


def test_a_reservation_object_of_the_wrong_type_is_refused() -> None:
    """Резервація — теж повернення порту, і теж не істина через анотацію."""
    from korpus.application.capability_gateway.effects import (
        InvalidEffectReservation,
        _attest_reservation,
    )
    from korpus.domain.models import Identity

    from apps.api.tests.test_capability_gateway_port_return_attestation import _request, _spec

    with pytest.raises(InvalidEffectReservation, match="invalid reservation type"):
        _attest_reservation(
            {"record": _record(), "created": True},
            identity=Identity(subject="writer", roles=frozenset({"admin"})),
            spec=_spec(),
            request=_request(),
            logical_resource="reference:1",
            invocation_id=INVOCATION,
            input_digest="sha256:" + "2" * 64,
            binding_digest=BINDING,
        )


def test_a_reservation_whose_created_flag_is_not_boolean_is_refused() -> None:
    """«Схоже на істину» не є `True`: 1 і True відрізняються саме тут."""
    from korpus.application.capability_gateway.effects import (
        InvalidEffectReservation,
        _attest_reservation,
    )
    from korpus.domain.models import Identity

    from apps.api.tests.test_capability_gateway_port_return_attestation import _request, _spec

    reservation = EffectReservation(record=_record(), created=True)
    object.__setattr__(reservation, "created", 1)
    with pytest.raises(InvalidEffectReservation, match="created flag is not boolean"):
        _attest_reservation(
            reservation,
            identity=Identity(subject="writer", roles=frozenset({"admin"})),
            spec=_spec(),
            request=_request(),
            logical_resource="reference:1",
            invocation_id=INVOCATION,
            input_digest="sha256:" + "2" * 64,
            binding_digest=BINDING,
        )


def _reconciled(**overrides: object) -> EffectRecord:
    base: dict[str, object] = {
        "state": EffectState.RECONCILED,
        "reconciliation_disposition": ReconciliationDisposition.CONFIRMED_COMMITTED,
        "provider_reference": "provider:42",
    }
    base.update(overrides)
    return _record(**base)


def test_a_reconciled_result_that_is_not_a_record_is_refused() -> None:
    """Узгодження теж повертає порт, і теж не є істиною через анотацію типу."""
    from korpus.application.capability_gateway.effects import attest_reconciled_effect

    with pytest.raises(InvalidEffectTransition, match="invalid reconciled record type"):
        attest_reconciled_effect(
            _record(),
            {"state": "RECONCILED"},
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference="provider:42",
        )


def test_reconciliation_that_changed_immutable_binding_is_refused() -> None:
    from korpus.application.capability_gateway.effects import attest_reconciled_effect

    with pytest.raises(InvalidEffectTransition, match="immutable reservation binding"):
        attest_reconciled_effect(
            _record(),
            _reconciled(logical_resource="reference:99"),
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference="provider:42",
        )


def test_reconciliation_that_did_not_persist_reconciled_state_is_refused() -> None:
    from korpus.application.capability_gateway.effects import attest_reconciled_effect

    updated = _record(state=EffectState.COMMITTED, provider_reference="provider:42")
    with pytest.raises(InvalidEffectTransition, match="did not persist RECONCILED"):
        attest_reconciled_effect(
            _record(),
            updated,
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference="provider:42",
        )


def test_reconciliation_with_a_different_disposition_is_refused() -> None:
    """Записане розпорядження мусить бути ТИМ, яке спостерігав провайдер."""
    from korpus.application.capability_gateway.effects import attest_reconciled_effect

    with pytest.raises(InvalidEffectTransition, match="disposition does not match"):
        attest_reconciled_effect(
            _record(),
            _reconciled(reconciliation_disposition=ReconciliationDisposition.CONFIRMED_NO_EFFECT),
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference="provider:42",
        )


def test_reconciliation_with_a_different_provider_reference_is_refused() -> None:
    from korpus.application.capability_gateway.effects import attest_reconciled_effect

    with pytest.raises(InvalidEffectTransition, match="provider reference does not match"):
        attest_reconciled_effect(
            _record(),
            _reconciled(provider_reference="provider:other"),
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference="provider:42",
        )


def test_a_faithful_reconciliation_is_accepted() -> None:
    """Негативний контроль: перевірки карають РОЗБІЖНІСТЬ, не саме узгодження."""
    from korpus.application.capability_gateway.effects import attest_reconciled_effect

    updated = _reconciled()
    assert (
        attest_reconciled_effect(
            _record(),
            updated,
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference="provider:42",
        )
        is updated
    )


def test_effect_binding_without_an_idempotency_key_is_refused() -> None:
    """Прив'язка ефекту без ключа ідемпотентності не адресує жодної резервації."""
    from korpus.application.capability_gateway.contracts import CapabilityContractError
    from korpus.application.capability_gateway.effects import effect_binding_digest
    from korpus.domain.models import Identity

    from apps.api.tests.test_capability_gateway_port_return_attestation import _request, _spec

    with pytest.raises(CapabilityContractError, match="requires an idempotency key"):
        effect_binding_digest(
            identity=Identity(subject="writer", roles=frozenset({"admin"})),
            spec=_spec(),
            request=_request(),
            logical_resource="reference:1",
        )


def _guard_kwargs(ledger: object, **overrides: object) -> dict[str, object]:
    from korpus.domain.models import Identity

    from apps.api.tests.test_capability_gateway_effects import _request as _effect_request
    from apps.api.tests.test_capability_gateway_effects import _spec as _effect_spec

    kwargs: dict[str, object] = {
        "identity": Identity(subject="writer", roles=frozenset({"admin"})),
        "spec": _effect_spec(),
        "request": _effect_request(),
        "logical_resource": "reference:1",
        "invocation_id": INVOCATION,
        "ledger": ledger,
        "explicit_effect_authorized": True,
    }
    kwargs.update(overrides)
    return kwargs


def test_an_effectful_invocation_without_an_idempotency_key_is_refused() -> None:
    """Ефектний виклик без ключа не має чим боронитись від повтору."""
    from korpus.application.capability_gateway.contracts import CapabilityContractError
    from korpus.application.capability_gateway.effects import prepare_effect_guard

    from apps.api.tests.test_capability_gateway_effects import _MemoryLedger
    from apps.api.tests.test_capability_gateway_effects import _request as _effect_request

    with pytest.raises(CapabilityContractError, match="requires an idempotency key"):
        prepare_effect_guard(
            **_guard_kwargs(_MemoryLedger(), request=_effect_request(key=None))  # type: ignore[arg-type]
        )


def test_a_ledger_returning_a_non_record_reservation_is_refused() -> None:
    """Порт віддав резервацію без запису — це не «порожній результат», це відмова."""
    from korpus.application.capability_gateway.effects import (
        InvalidEffectReservation,
        prepare_effect_guard,
    )

    class _Broken:
        def reserve(self, **kwargs: object) -> EffectReservation:
            reservation = EffectReservation(record=_record(), created=True)
            object.__setattr__(reservation, "record", {"state": "PENDING"})
            return reservation

    with pytest.raises(InvalidEffectReservation, match="invalid record type"):
        prepare_effect_guard(**_guard_kwargs(_Broken()))  # type: ignore[arg-type]


def test_a_ledger_returning_a_non_canonical_state_is_refused() -> None:
    """Стан поза перелічення — не «інший стан», а неканонічний."""
    from korpus.application.capability_gateway.effects import (
        InvalidEffectReservation,
        prepare_effect_guard,
    )

    class _Broken:
        def reserve(self, **kwargs: object) -> EffectReservation:
            # Запис будується З САМИХ АРГУМЕНТІВ: інакше спрацьовує попередня перевірка
            # прив'язки, і тест міряв би не ту умову.
            record = EffectRecord(
                subject_id=kwargs["subject_id"],  # type: ignore[arg-type]
                idempotency_key=kwargs["idempotency_key"],  # type: ignore[arg-type]
                binding_digest=kwargs["binding_digest"],  # type: ignore[arg-type]
                invocation_id=kwargs["invocation_id"],  # type: ignore[arg-type]
                capability_id=kwargs["capability_id"],  # type: ignore[arg-type]
                capability_version=kwargs["capability_version"],  # type: ignore[arg-type]
                logical_resource=kwargs["logical_resource"],  # type: ignore[arg-type]
                input_digest=kwargs["input_digest"],  # type: ignore[arg-type]
                state=EffectState.PENDING,
            )
            object.__setattr__(record, "state", "PENDING")
            return EffectReservation(record=record, created=False)

    with pytest.raises(InvalidEffectReservation, match="state is not canonical"):
        prepare_effect_guard(**_guard_kwargs(_Broken()))  # type: ignore[arg-type]
