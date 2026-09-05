from __future__ import annotations

import pytest

from korpus.application.capability_gateway.errors import CapabilityRegistrationError
from korpus.application.capability_gateway.validation import ExactSchemaRegistry


def test_schema_registry_rejects_noncallable_validator_at_composition_boundary() -> None:
    registry = ExactSchemaRegistry()

    with pytest.raises(CapabilityRegistrationError, match="validator must be callable"):
        registry.register("urn:korpus:test:invalid-validator:v1", object())  # type: ignore[arg-type]


def test_schema_registry_rejects_nonstr_schema_identity_as_registration_error() -> None:
    registry = ExactSchemaRegistry()

    with pytest.raises(CapabilityRegistrationError, match="schema id must be a string"):
        registry.register(1, lambda value: None)  # type: ignore[arg-type]


def test_schema_registry_accepts_callable_validator() -> None:
    seen: list[object] = []
    registry = ExactSchemaRegistry()
    registry.register("urn:korpus:test:valid-validator:v1", seen.append)

    registry.validate("urn:korpus:test:valid-validator:v1", {"value": 1})

    assert seen == [{"value": 1}]
