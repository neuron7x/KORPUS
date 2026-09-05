from __future__ import annotations

from collections.abc import Iterable

from korpus.application.capability_gateway.errors import (
    CapabilityNotFound,
    CapabilityRegistrationError,
    CapabilityUnavailable,
)
from korpus.application.capability_gateway.types import CapabilityLifecycle, CapabilitySpec

CapabilityKey = tuple[str, str]


class CapabilityRegistry:
    """In-memory canonical registry for one process.

    Registration is exact and immutable by `(capability_id, version)`. Executable lookup
    refuses every lifecycle state except `ENABLED`; callers must never silently select a
    latest version or use a discovered provider declaration as authority.
    """

    def __init__(self, specs: Iterable[CapabilitySpec] = ()) -> None:
        self._specs: dict[CapabilityKey, CapabilitySpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: CapabilitySpec) -> None:
        key = self._key(spec.capability_id, spec.version)
        if key in self._specs:
            raise CapabilityRegistrationError(
                f"duplicate capability declaration: {spec.capability_id}@{spec.version}"
            )
        self._specs[key] = spec

    def describe_exact(self, capability_id: str, version: str) -> CapabilitySpec:
        try:
            return self._specs[self._key(capability_id, version)]
        except KeyError as exc:
            raise CapabilityNotFound(f"unknown capability: {capability_id}@{version}") from exc

    def resolve_exact(self, capability_id: str, version: str) -> CapabilitySpec:
        spec = self.describe_exact(capability_id, version)
        if spec.lifecycle is not CapabilityLifecycle.ENABLED:
            raise CapabilityUnavailable(
                f"capability is {spec.lifecycle.value.lower()}: {capability_id}@{version}"
            )
        return spec

    def versions(self, capability_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(version for registered_id, version in self._specs if registered_id == capability_id)
        )

    def all_specs(self) -> tuple[CapabilitySpec, ...]:
        return tuple(self._specs[key] for key in sorted(self._specs))

    @staticmethod
    def _key(capability_id: str, version: str) -> CapabilityKey:
        return capability_id, version
