from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
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

    Canonical capability metadata is resolved only from a frozen composition snapshot for
    bounded telemetry dimensions. Later mutation of the caller-owned registry cannot make
    telemetry describe a runtime-rejected capability as admitted. Telemetry remains lossy:
    failures never authorize, block, replace, suppress, or rewrite gateway results.
    """

    def __init__(
        self,
        gateway: CapabilityGateway,
        registry: CapabilityRegistry,
        telemetry: CapabilityInvocationTelemetry,
    ) -> None:
        self._gateway = gateway
        self._registry = registry.frozen_snapshot()
        self._telemetry = telemetry

    def invoke(self, *, identity: Identity, request: IntegrationRequest) -> IntegrationResult:
        spec = self._resolved_for_telemetry(request)
        started = time.monotonic()
        with _lossy_telemetry_span(self._telemetry, spec):
            result = self._gateway.invoke(identity=identity, request=request)
        self._observe_lossy(
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
        except Exception:
            return None

    def _observe_lossy(
        self,
        *,
        spec: CapabilitySpec | None,
        result: IntegrationResult,
        duration_seconds: float,
    ) -> None:
        try:
            self._telemetry.observe_invocation(
                spec=spec,
                result=result,
                duration_seconds=duration_seconds,
            )
        except Exception:
            return


@contextmanager
def _lossy_telemetry_span(
    telemetry: CapabilityInvocationTelemetry,
    spec: CapabilitySpec | None,
) -> Iterator[None]:
    manager: AbstractContextManager[object] | None = None
    try:
        manager = telemetry.invocation_span(spec)
        manager.__enter__()
    except Exception:
        manager = None

    if manager is None:
        yield
        return

    try:
        yield
    except BaseException as exc:
        try:
            manager.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:
            pass
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception:
            pass
