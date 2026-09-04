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


class AdapterKnownNoEffect(RuntimeError):
    reason = "adapter_known_no_effect"


class AdapterOutcomeUnknown(RuntimeError):
    reason = "adapter_outcome_unknown"


class AdapterExecutionFailed(RuntimeError):
    reason = "adapter_execution_failed"


@dataclass(frozen=True, slots=True)
class AdapterExecutionResult:
    output: object
    evidence: EvidenceEnvelope | None = None
    provider_receipt: object | None = None


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
    """Exact adapter implementation registry owned by server composition."""

    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], CapabilityAdapter] = {}

    def register(self, adapter_id: str, adapter_version: str, adapter: CapabilityAdapter) -> None:
        key = adapter_id.strip(), adapter_version.strip()
        if not all(key):
            raise CapabilityRegistrationError("adapter id/version must be non-empty")
        if key in self._adapters:
            raise CapabilityRegistrationError(
                f"duplicate adapter implementation: {adapter_id}@{adapter_version}"
            )
        self._adapters[key] = adapter

    def resolve(self, spec: CapabilitySpec) -> CapabilityAdapter:
        key = spec.adapter.adapter_id, spec.adapter.adapter_version
        try:
            return self._adapters[key]
        except KeyError as exc:
            raise CapabilityNotFound(
                f"adapter implementation not registered: {key[0]}@{key[1]}"
            ) from exc
