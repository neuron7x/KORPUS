from __future__ import annotations

from collections.abc import Callable, Mapping

from korpus.application.capability_gateway.errors import (
    CapabilityContractError,
    CapabilityRegistrationError,
)

SchemaCheck = Callable[[object], None]


class ExactSchemaRegistry:
    """Server-owned exact schema-id registry.

    Runtime composition consumes a frozen snapshot. The caller may continue assembling its
    own registry, but those later registrations cannot silently alter an already admitted
    gateway instance.
    """

    def __init__(self, validators: Mapping[str, SchemaCheck] | None = None) -> None:
        self._validators: dict[str, SchemaCheck] = {}
        self._frozen = False
        for schema_id, validator in (validators or {}).items():
            self.register(schema_id, validator)

    def register(self, schema_id: str, validator: SchemaCheck) -> None:
        if self._frozen:
            raise CapabilityRegistrationError("schema registry snapshot is frozen")
        normalized = schema_id.strip()
        if not normalized:
            raise CapabilityRegistrationError("schema id must be non-empty")
        if normalized in self._validators:
            raise CapabilityRegistrationError(f"duplicate schema id: {normalized}")
        self._validators[normalized] = validator

    def frozen_snapshot(self) -> ExactSchemaRegistry:
        snapshot = ExactSchemaRegistry(self._validators)
        snapshot._frozen = True
        return snapshot

    def validate(self, schema_id: str, value: object) -> None:
        try:
            validator = self._validators[schema_id]
        except KeyError as exc:
            raise CapabilityContractError(f"unknown schema id: {schema_id}") from exc
        try:
            result = validator(value)
        except CapabilityContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise CapabilityContractError(f"schema validation failed: {schema_id}") from exc
        if result is not None:
            raise RuntimeError("schema validator returned a non-None success sentinel")

    def schema_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._validators))
