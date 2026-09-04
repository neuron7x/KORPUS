from __future__ import annotations

from types import TracebackType
from typing import Literal
from uuid import UUID

import pytest

from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.invoke import IntegrationResult
from korpus.application.capability_gateway.observed import ObservedCapabilityGateway
from korpus.application.capability_gateway.registry import CapabilityRegistry
from korpus.application.capability_gateway.types import IntegrationRequest
from korpus.domain.models import Identity


class _Gateway:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def invoke(self, *, identity: Identity, request: IntegrationRequest) -> IntegrationResult:
        del identity, request
        self.calls += 1
        if self.error is not None:
            raise self.error
        return IntegrationResult(
            invocation_id=UUID("11111111-1111-1111-1111-111111111111"),
            outcome=InvocationOutcome.DENIED,
            error_code="CAPABILITY_UNKNOWN",
        )


class _Span:
    def __init__(self, mode: str) -> None:
        self.mode = mode

    def __enter__(self) -> object:
        if self.mode == "enter":
            raise RuntimeError("telemetry enter failed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_type, exc, traceback
        if self.mode == "exit":
            raise RuntimeError("telemetry exit failed")
        return False


class _Telemetry:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.specs: list[object | None] = []

    def invocation_span(self, spec: object | None) -> _Span:
        self.specs.append(spec)
        if self.mode == "factory":
            raise RuntimeError("telemetry span factory failed")
        return _Span(self.mode)

    def observe_invocation(self, **kwargs: object) -> None:
        self.specs.append(kwargs["spec"])
        if self.mode == "observe":
            raise RuntimeError("telemetry observation failed")


class _ExplodingRegistry:
    def resolve_exact(self, capability_id: str, capability_version: str) -> object:
        del capability_id, capability_version
        raise RuntimeError("telemetry-only registry lookup failed")


def _request() -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.telemetry.read",
        capability_version="1.0.0",
        input={"reference_id": "1"},
    )


@pytest.mark.parametrize("mode", ["factory", "enter", "exit", "observe"])
def test_telemetry_failures_never_block_or_replace_gateway_result(
    mode: Literal["factory", "enter", "exit", "observe"],
) -> None:
    gateway = _Gateway()
    wrapper = ObservedCapabilityGateway(  # type: ignore[arg-type]
        gateway,
        CapabilityRegistry(),
        _Telemetry(mode),
    )

    result = wrapper.invoke(identity=Identity(subject="reader"), request=_request())

    assert gateway.calls == 1
    assert result.outcome is InvocationOutcome.DENIED
    assert result.error_code == "CAPABILITY_UNKNOWN"


def test_telemetry_registry_failure_degrades_to_unknown_metadata_only() -> None:
    gateway = _Gateway()
    telemetry = _Telemetry("ok")
    wrapper = ObservedCapabilityGateway(  # type: ignore[arg-type]
        gateway,
        _ExplodingRegistry(),
        telemetry,
    )

    result = wrapper.invoke(identity=Identity(subject="reader"), request=_request())

    assert gateway.calls == 1
    assert result.outcome is InvocationOutcome.DENIED
    assert telemetry.specs == [None, None]


def test_telemetry_exit_failure_never_masks_canonical_gateway_exception() -> None:
    gateway = _Gateway(error=ValueError("canonical gateway failure"))
    wrapper = ObservedCapabilityGateway(  # type: ignore[arg-type]
        gateway,
        CapabilityRegistry(),
        _Telemetry("exit"),
    )

    with pytest.raises(ValueError, match="canonical gateway failure"):
        wrapper.invoke(identity=Identity(subject="reader"), request=_request())

    assert gateway.calls == 1
