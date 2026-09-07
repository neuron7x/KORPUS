from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from typing import Protocol

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

    The legacy registry argument is retained for call-site compatibility, but it is not an
    admissible source of runtime capability identity: it can be independently populated or
    mutated and therefore cannot prove that it is the exact frozen registry consumed by the
    gateway. Until the runtime exposes an explicit immutable metadata view, capability
    attribution deliberately abstains (`spec=None`). Outcome/error telemetry remains useful
    and bounded, while false operational evidence is impossible by construction.

    Telemetry is deliberately lossy: its failures never authorize, block, replace, suppress,
    or rewrite gateway results.
    """

    def __init__(
        self,
        gateway: CapabilityGateway,
        registry: CapabilityRegistry,
        telemetry: CapabilityInvocationTelemetry,
    ) -> None:
        self._gateway = gateway
        self._telemetry = telemetry
        # Do not derive operational evidence from an independently supplied registry. Keeping
        # the argument avoids a compatibility break while the runtime-bound metadata view is
        # designed explicitly.
        del registry

    def invoke(self, *, identity: Identity, request: IntegrationRequest) -> IntegrationResult:
        spec: CapabilitySpec | None = None
        started = time.monotonic()
        with _lossy_telemetry_span(self._telemetry, spec):
            result = self._gateway.invoke(identity=identity, request=request)
        self._observe_lossy(
            spec=spec,
            result=result,
            duration_seconds=max(0.0, time.monotonic() - started),
        )
        return result

    def _observe_lossy(
        self,
        *,
        spec: CapabilitySpec | None,
        result: IntegrationResult,
        duration_seconds: float,
    ) -> None:
        # `telemetry` is an injected Protocol. Prometheus clients, OTLP exporters and test
        # doubles all satisfy it and share no exception base this module could name without
        # taking a dependency on the exporter it is supposed to be independent of. The blind
        # catch is the contract, not an oversight: telemetry is lossy by declaration, and
        # test_capability_gateway_observability_isolation.py drives a RuntimeError through
        # every one of the four telemetry entry points to prove the gateway result survives.
        # LOSSY-BY-CONTRACT: test_capability_gateway_observability_isolation.py
        with suppress(Exception):
            self._telemetry.observe_invocation(
                spec=spec,
                result=result,
                duration_seconds=duration_seconds,
            )


@contextmanager
def _lossy_telemetry_span(
    telemetry: CapabilityInvocationTelemetry,
    spec: CapabilitySpec | None,
) -> Iterator[None]:
    manager: AbstractContextManager[object] | None = None
    try:
        manager = telemetry.invocation_span(spec)
        manager.__enter__()
    except Exception:  # noqa: BLE001 - injected telemetry Protocol, see _observe_lossy
        # A span factory or __enter__ that fails means "no span", never "no invocation".
        # LOSSY-BY-CONTRACT: test_capability_gateway_observability_isolation.py
        manager = None

    if manager is None:
        yield
        return

    try:
        yield
    except BaseException as exc:
        # __exit__ belongs to the same injected span object: a failure to close it may not
        # replace, suppress or outrank the exception the gateway is already propagating.
        # LOSSY-BY-CONTRACT: test_capability_gateway_observability_isolation.py
        with suppress(Exception):
            manager.__exit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        # LOSSY-BY-CONTRACT: test_capability_gateway_observability_isolation.py
        with suppress(Exception):
            manager.__exit__(None, None, None)
