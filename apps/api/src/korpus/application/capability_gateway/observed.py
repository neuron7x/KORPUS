from __future__ import annotations

import time
from contextlib import AbstractContextManager
from typing import Protocol

from korpus.application.capability_gateway.errors import CapabilityNotFound, CapabilityUnavailable
from korpus.application.capability_gateway.invoke import CapabilityGateway, IntegrationResult
from korpus.application.capability_gateway.registry import CapabilityRegistry
from korpus.application.capability_gateway.types import CapabilitySpec, IntegrationRequest
from korpus.domain.models import Identity


class CapabilityInvocationTelemetry(Protocol):
    """Lossy operational telemetry; never an authorization or audit authority."""

    def invocation_span(self, spec: CapabilitySpec | None) -> AbstractContextManager[object]: ...

    def observe_invocation(
        self,
        *,
        spec: CapabilitySpec | None,
        result: IntegrationResult,
        duration_seconds: float,
    ) -> None: ...


class ObservedCapabilityGateway:
    """Telemetry decorator preserving the exact gateway decision path.

    Canonical capability metadata is resolved only for bounded telemetry dimensions. A
    caller-controlled unknown capability id is deliberately represented as `spec=None` so
    it cannot create unbounded metric labels or trace attributes.
    """

    def __init__(
        self,
        gateway: CapabilityGateway,
        registry: CapabilityRegistry,
        telemetry: CapabilityInvocationTelemetry,
    ) -> None:
        self._gateway = gateway
        self._registry = registry
        self._telemetry = telemetry

    def invoke(self, *, identity: Identity, request: IntegrationRequest) -> IntegrationResult:
        spec = self._resolved_for_telemetry(request)
        started = time.monotonic()
        with self._telemetry.invocation_span(spec):
            result = self._gateway.invoke(identity=identity, request=request)
        self._telemetry.observe_invocation(
            spec=spec,
            result=result,
            duration_seconds=max(0.0, time.monotonic() - started),
        )
        return result

    def _resolved_for_telemetry(self, request: IntegrationRequest) -> CapabilitySpec | None:
        try:
            return self._registry.resolve_exact(request.capability_id, request.capability_version)
        except (CapabilityNotFound, CapabilityUnavailable):
            return None
