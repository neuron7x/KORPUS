from __future__ import annotations

import pytest

from korpus.application.capability_gateway.adapters import AdapterRegistry
from korpus.application.capability_gateway.errors import CapabilityRegistrationError


class _ValidAdapter:
    def execute(self, **kwargs: object) -> object:
        return kwargs


class _NonCallableAdapter:
    execute = 1


class _ExplodingExecuteDescriptor:
    @property
    def execute(self) -> object:
        raise RuntimeError("descriptor must not escape composition validation")


def test_adapter_registry_rejects_missing_execute_at_composition_boundary() -> None:
    registry = AdapterRegistry()

    with pytest.raises(CapabilityRegistrationError, match="callable execute"):
        registry.register("custom.missing", "1.0.0", object())  # type: ignore[arg-type]


def test_adapter_registry_rejects_noncallable_execute() -> None:
    registry = AdapterRegistry()

    with pytest.raises(CapabilityRegistrationError, match="callable execute"):
        registry.register("custom.invalid", "1.0.0", _NonCallableAdapter())  # type: ignore[arg-type]


def test_adapter_registry_normalizes_execute_descriptor_failure_to_registration_error() -> None:
    registry = AdapterRegistry()

    with pytest.raises(CapabilityRegistrationError, match="callable execute"):
        registry.register(
            "custom.descriptor",
            "1.0.0",
            _ExplodingExecuteDescriptor(),  # type: ignore[arg-type]
        )


def test_adapter_registry_accepts_callable_execute() -> None:
    registry = AdapterRegistry()
    adapter = _ValidAdapter()

    registry.register("custom.valid", "1.0.0", adapter)  # type: ignore[arg-type]

    with pytest.raises(CapabilityRegistrationError, match="duplicate adapter implementation"):
        registry.register("custom.valid", "1.0.0", adapter)  # type: ignore[arg-type]
