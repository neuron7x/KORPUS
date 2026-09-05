from __future__ import annotations

from collections.abc import Callable, Mapping

from korpus.application.capability_gateway.errors import (
    CapabilityContractError,
    CapabilityRegistrationError,
)

SchemaCheck = Callable[[object], None]


class ExactSchemaRegistry:
    """Server-owned exact schema-id registry.

    Capability manifests name schemas; they never provide executable validators. Unknown
    schema ids fail closed and registration is immutable per id for the process lifetime.
    """

    def __init__(self, validators: Mapping[str, SchemaCheck] | None = None) -> None:
        self._validators: dict[str, SchemaCheck] = {}
        for schema_id, validator in (validators or {}).items():
            self.register(schema_id, validator)

    def register(self, schema_id: str, validator: SchemaCheck) -> None:
        normalized = schema_id.strip()
        if not normalized:
            raise CapabilityRegistrationError("schema id must be non-empty")
        if normalized in self._validators:
            raise CapabilityRegistrationError(f"duplicate schema id: {normalized}")
        self._validators[normalized] = validator

    def validate(self, schema_id: str, value: object) -> None:
        try:
            validator = self._validators[schema_id]
        except KeyError as exc:
            raise CapabilityContractError(f"unknown schema id: {schema_id}") from exc
        try:
            validator(value)
        except CapabilityContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise CapabilityContractError(f"schema validation failed: {schema_id}") from exc

    def schema_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._validators))
