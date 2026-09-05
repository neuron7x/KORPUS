from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from korpus.application.capability_gateway.errors import (
    CapabilityNotFound,
    CapabilityRegistrationError,
)
from korpus.application.capability_gateway.evidence import EvidenceEnvelope
from korpus.application.capability_gateway.types import (
    CapabilitySpec,
    IntegrationRequest,
    InvocationContext,
)

_MAX_PROVIDER_REFERENCE_LENGTH = 512


def _validate_provider_reference(value: str | None) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError("provider reference must be a non-blank string")
    if len(value) > _MAX_PROVIDER_REFERENCE_LENGTH:
        raise ValueError("provider reference exceeds maximum length")


class AdapterKnownNoEffect(RuntimeError):
    reason = "adapter_known_no_effect"


class AdapterOutcomeUnknown(RuntimeError):
    reason = "adapter_outcome_unknown"

    def __init__(self, message: str, *, provider_reference: str | None = None) -> None:
        _validate_provider_reference(provider_reference)
        self.provider_reference = provider_reference
        super().__init__(message)


class AdapterExecutionFailed(RuntimeError):
    reason = "adapter_execution_failed"

    def __init__(self, message: str, *, provider_reference: str | None = None) -> None:
        _validate_provider_reference(provider_reference)
        self.provider_reference = provider_reference
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class AdapterExecutionResult:
    output: object
    evidence: EvidenceEnvelope | None = None
    provider_receipt: object | None = None
    provider_reference: str | None = None

    def __post_init__(self) -> None:
        _validate_provider_reference(self.provider_reference)


class CapabilityAdapter(Protocol):
    def execute(
        self,
        *,
        spec: CapabilitySpec,
        request: IntegrationRequest,
        context: InvocationContext,
        logical_resource: str,
    ) -> AdapterExecutionResult: ...


class AdapterRegistry:
    """Exact adapter registry; runtime composition consumes a frozen identity snapshot."""

    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], CapabilityAdapter] = {}
        self._frozen = False

    def register(self, adapter_id: str, adapter_version: str, adapter: CapabilityAdapter) -> None:
        if self._frozen:
            raise CapabilityRegistrationError("adapter registry snapshot is frozen")
        key = adapter_id.strip(), adapter_version.strip()
        if not all(key):
            raise CapabilityRegistrationError("adapter id/version must be non-empty")
        if key in self._adapters:
            raise CapabilityRegistrationError(
                f"duplicate adapter implementation: {adapter_id}@{adapter_version}"
            )
        self._adapters[key] = adapter

    def frozen_snapshot(self) -> AdapterRegistry:
        snapshot = AdapterRegistry()
        snapshot._adapters = dict(self._adapters)
        snapshot._frozen = True
        return snapshot

    def resolve(self, spec: CapabilitySpec) -> CapabilityAdapter:
        key = spec.adapter.adapter_id, spec.adapter.adapter_version
        try:
            return self._adapters[key]
        except KeyError as exc:
            raise CapabilityNotFound(
                f"adapter implementation not registered: {key[0]}@{key[1]}"
            ) from exc
