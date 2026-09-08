"""Заморожений знімок реєстру не приймає реєстрацій — і кожен реєстр це доводить.

Шлюз бере знімок реєстрів на час виклику: спроможності, адаптери, схеми. Знімок
заморожений НЕ для зручності — реєстрація під час виконання змінила б множину, за якою
вже ухвалено рішення про допуск. Виміряно 08.09.2026: три реєстри, і в кожному ця
відмова була непройденою.
"""

from __future__ import annotations

import pytest
from korpus.application.capability_gateway.adapters import AdapterRegistry
from korpus.application.capability_gateway.errors import CapabilityRegistrationError
from korpus.application.capability_gateway.registry import CapabilityRegistry
from korpus.application.capability_gateway.validation import ExactSchemaRegistry

from apps.api.tests.test_capability_gateway_http_adapter import _spec


class _Adapter:
    def execute(self, **kwargs: object) -> object:
        return kwargs


def test_a_frozen_capability_registry_refuses_registration() -> None:
    snapshot = CapabilityRegistry([_spec()]).frozen_snapshot()
    with pytest.raises(CapabilityRegistrationError, match="frozen"):
        snapshot.register(_spec())


def test_a_frozen_adapter_registry_refuses_registration() -> None:
    registry = AdapterRegistry()
    registry.register("http.reference", "1.0.0", _Adapter())
    with pytest.raises(CapabilityRegistrationError, match="frozen"):
        registry.frozen_snapshot().register("http.other", "1.0.0", _Adapter())


def test_a_frozen_schema_registry_refuses_registration() -> None:
    registry = ExactSchemaRegistry({"urn:a": lambda value: None})
    with pytest.raises(CapabilityRegistrationError, match="frozen"):
        registry.frozen_snapshot().register("urn:b", lambda value: None)


def test_an_unfrozen_registry_still_accepts_registration() -> None:
    """Негативний контроль: правило карає ЗАМОРОЖЕНІСТЬ, а не реєстрацію."""
    registry = AdapterRegistry()
    registry.register("http.reference", "1.0.0", _Adapter())
    assert registry.resolve(_spec()) is not None


@pytest.mark.parametrize(
    ("adapter_id", "adapter_version"),
    [(7, "1.0.0"), ("http.reference", 7), ("", "1.0.0"), ("http.reference", "")],
)
def test_an_adapter_key_that_is_not_two_non_empty_strings_is_refused(
    adapter_id: object, adapter_version: object
) -> None:
    """Ключ адаптера — пара рядків. Порожній бік робить резолвінг неоднозначним."""
    with pytest.raises((CapabilityRegistrationError, ValueError, TypeError)):
        AdapterRegistry().register(adapter_id, adapter_version, _Adapter())  # type: ignore[arg-type]


@pytest.mark.parametrize("schema_id", ["", "   "])
def test_an_empty_schema_id_is_refused(schema_id: str) -> None:
    with pytest.raises(CapabilityRegistrationError, match="non-empty"):
        ExactSchemaRegistry().register(schema_id, lambda value: None)
