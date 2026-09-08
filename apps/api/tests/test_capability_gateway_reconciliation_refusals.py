"""Відмови узгодження невизначеного ефекту — кожна окремим входом.

`reconcile_unknown_effect` визначає стан дії, чий наслідок лишився невідомим, НЕ
повторюючи саму дію. Тому кожна його відмова — це межа, за якою неоднозначність не
має права перетворитись на «все гаразд». Виміряно 08.09.2026: 10 непокритих гілок, і
всі вони — саме ці межі, разом із перевіркою входу самого розпорядження.

Фікстури беруться з `test_capability_gateway_reconciliation`: друга копія розійшлася б
із першою мовчки.
"""

from __future__ import annotations

import pytest
from korpus.application.capability_gateway.effects import ReconciliationDisposition
from korpus.application.capability_gateway.reconciliation import (
    ReconciliationConflict,
    ReconciliationIndeterminate,
    ReconciliationObservation,
)

from apps.api.tests.test_capability_gateway_reconciliation import (
    _Ledger,
    _reconcile,
    _record,
    _Resolver,
    _safety,
    _spec,
)

BINDING = "sha256:" + "1" * 64


@pytest.mark.parametrize("disposition", ["CONFIRMED_COMMITTED", 7, None])
def test_a_disposition_that_is_not_a_registered_enum_is_refused(disposition: object) -> None:
    """Рядок, схожий на розпорядження, розпорядженням не є."""
    with pytest.raises(ValueError):
        ReconciliationObservation(disposition=disposition)  # type: ignore[arg-type]


@pytest.mark.parametrize("reference", ["", "   ", 7, "x" * 513])
def test_a_provider_reference_that_is_not_a_bounded_string_is_refused(reference: object) -> None:
    with pytest.raises(ValueError):
        ReconciliationObservation(
            disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
            provider_reference=reference,  # type: ignore[arg-type]
        )


def test_a_bounded_reference_is_accepted() -> None:
    """Негативний контроль: правило карає НЕГІДНЕ посилання, не наявність посилання."""
    request = ReconciliationObservation(
        disposition=ReconciliationDisposition.CONFIRMED_NO_EFFECT,
        provider_reference="provider:transaction:42",
    )
    assert request.provider_reference == "provider:transaction:42"


@pytest.mark.parametrize("key", ["", "   "])
def test_a_blank_idempotency_key_is_a_conflict(key: str) -> None:
    """Порожній ключ не адресує жодної резервації — це конфлікт, не порожній пошук."""
    from korpus.application.capability_gateway.reconciliation import reconcile_unknown_effect
    from korpus.domain.models import Identity

    spec = _spec()
    with pytest.raises(ReconciliationConflict):
        reconcile_unknown_effect(
            identity=Identity(subject="writer", roles=frozenset({"admin"})),
            spec=spec,
            idempotency_key=key,
            expected_binding_digest=BINDING,
            authorized=True,
            ledger=_Ledger(_record()),
            resolver=_Resolver(),
            effect_safety=_safety(spec),
        )


def test_an_empty_binding_digest_is_a_conflict() -> None:
    ledger = _Ledger(_record())
    with pytest.raises(ReconciliationConflict):
        _reconcile(ledger=ledger, resolver=_Resolver(), binding="")


def test_a_reservation_that_does_not_exist_is_a_conflict() -> None:
    with pytest.raises(ReconciliationConflict):
        _reconcile(ledger=_Ledger(None), resolver=_Resolver())


def test_a_ledger_that_cannot_answer_preserves_ambiguity() -> None:
    """Недоступний реєстр — НЕ «дії не було». Неоднозначність мусить пережити збій.

    Це найтонша з відмов: тихе `None` тут читалось би як «резервації немає», і
    невизначений наслідок став би визначеним через несправність сховища.
    """

    class _Unavailable(_Ledger):
        def get(self, *, subject_id: str, idempotency_key: str):
            raise OSError("durable store unavailable")

    with pytest.raises(ReconciliationIndeterminate):
        _reconcile(ledger=_Unavailable(_record()), resolver=_Resolver())


def test_an_observation_without_a_provider_reference_is_accepted() -> None:
    """Провайдер може підтвердити наслідок, не назвавши свого посилання."""
    observation = ReconciliationObservation(
        disposition=ReconciliationDisposition.CONFIRMED_NO_EFFECT
    )
    assert observation.provider_reference is None


def test_a_record_bound_to_another_subject_is_a_conflict() -> None:
    """Реєстр міг віддати чужий запис; звіряння суб'єкта — окрема межа, не наслідок пошуку."""

    class _Careless(_Ledger):
        def get(self, *, subject_id: str, idempotency_key: str):
            del subject_id, idempotency_key
            return self.record

    foreign = _record()
    object.__setattr__(foreign, "subject_id", "someone-else")
    ledger = _Careless(foreign)
    with pytest.raises(ReconciliationConflict, match="subject binding mismatch"):
        _reconcile(ledger=ledger, resolver=_Resolver())


def test_a_resolver_whose_mode_is_not_an_enum_is_a_conflict() -> None:
    """Рядок «PROVIDER_STATUS_QUERY» дорівнював би режимові лише на вигляд."""
    resolver = _Resolver()
    resolver.reconciliation_mode = "PROVIDER_STATUS_QUERY"  # type: ignore[assignment]

    with pytest.raises(ReconciliationConflict, match="resolver mode is invalid"):
        _reconcile(ledger=_Ledger(_record()), resolver=resolver)


def test_a_resolver_that_declares_indeterminacy_keeps_its_own_verdict() -> None:
    """Резольвер, який САМ каже «не знаю», не має бути переказаний загальним «не вирішив»."""
    resolver = _Resolver(error=ReconciliationIndeterminate("provider is mid-failover"))

    with pytest.raises(ReconciliationIndeterminate, match="mid-failover"):
        _reconcile(ledger=_Ledger(_record()), resolver=resolver)


def test_an_observation_of_the_wrong_type_preserves_ambiguity() -> None:
    """Резольвер — впорскуваний порт: анотація не доводить, що він повернув спостереження."""

    class _WrongShape(_Resolver):
        def observe(self, **kwargs: object) -> ReconciliationObservation:
            del kwargs
            return {"disposition": "CONFIRMED_COMMITTED"}  # type: ignore[return-value]

    with pytest.raises(ReconciliationIndeterminate, match="invalid observation"):
        _reconcile(ledger=_Ledger(_record()), resolver=_WrongShape())


def test_a_conflict_raised_by_the_durable_compare_and_set_is_not_rewritten() -> None:
    """Реєстр уже назвав ТОЧНУ причину розходження — загальне «CAS failed» стерло б її."""

    class _Conflicting(_Ledger):
        def reconcile(self, **kwargs: object):
            del kwargs
            raise ReconciliationConflict("effect was reconciled by a concurrent operator")

    with pytest.raises(ReconciliationConflict, match="concurrent operator"):
        _reconcile(ledger=_Conflicting(_record()), resolver=_Resolver())
