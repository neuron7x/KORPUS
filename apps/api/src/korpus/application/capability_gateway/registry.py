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
    """Exact server-owned capability registry.

    Registration is immutable by `(capability_id, version)`. Runtime composition consumes a
    frozen snapshot so later mutations of a caller-owned registry cannot widen an already
    admitted gateway instance or invalidate its effect-safety proof.
    """

    def __init__(self, specs: Iterable[CapabilitySpec] = ()) -> None:
        self._specs: dict[CapabilityKey, CapabilitySpec] = {}
        self._frozen = False
        for spec in specs:
            self.register(spec)

    def register(self, spec: CapabilitySpec) -> None:
        if self._frozen:
            raise CapabilityRegistrationError("capability registry snapshot is frozen")
        key = self._key(spec.capability_id, spec.version)
        if key in self._specs:
            raise CapabilityRegistrationError(
                f"duplicate capability declaration: {spec.capability_id}@{spec.version}"
            )
        self._specs[key] = spec

    def frozen_snapshot(self) -> CapabilityRegistry:
        snapshot = CapabilityRegistry(self.all_specs())
        snapshot._frozen = True
        return snapshot

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
