from __future__ import annotations

from contextlib import nullcontext
from uuid import UUID

from prometheus_client import CollectorRegistry

from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.invoke import IntegrationResult
from korpus.application.capability_gateway.observed import ObservedCapabilityGateway
from korpus.application.capability_gateway.registry import CapabilityRegistry
from korpus.application.capability_gateway.types import IntegrationRequest
from korpus.domain.models import Identity
from korpus.infrastructure.capability_observability import CapabilityObservability
from korpus.infrastructure.observability import Observability


class _Gateway:
    def invoke(self, *, identity: Identity, request: IntegrationRequest) -> IntegrationResult:
        del identity, request
        return IntegrationResult(
            invocation_id=UUID("33333333-3333-3333-3333-333333333333"),
            outcome=InvocationOutcome.DENIED,
            error_code="CAPABILITY_UNKNOWN",
        )


class _Telemetry:
    def __init__(self) -> None:
        self.specs: list[object | None] = []

    def invocation_span(self, spec: object | None) -> object:
        self.specs.append(spec)
        return nullcontext()

    def observe_invocation(self, **kwargs: object) -> None:
        self.specs.append(kwargs["spec"])


def _unknown_request() -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="attacker.unbounded.label.value",
        capability_version="999.999.999",
        input={"secret": "must-not-enter-telemetry"},
    )


def test_observed_gateway_never_promotes_unknown_request_id_into_telemetry_spec() -> None:
    telemetry = _Telemetry()
    wrapper = ObservedCapabilityGateway(  # type: ignore[arg-type]
        _Gateway(), CapabilityRegistry(), telemetry  # type: ignore[arg-type]
    )

    result = wrapper.invoke(identity=Identity(subject="reader"), request=_unknown_request())

    assert result.error_code == "CAPABILITY_UNKNOWN"
    assert telemetry.specs == [None, None]


def test_prometheus_dimensions_are_bounded_and_exclude_request_identity() -> None:
    registry = CollectorRegistry(auto_describe=True)
    observability = Observability(registry=registry)
    telemetry = CapabilityObservability(observability)
    result = IntegrationResult(
        invocation_id=UUID("44444444-4444-4444-4444-444444444444"),
        outcome=InvocationOutcome.DENIED,
        error_code="CAPABILITY_UNKNOWN",
    )

    telemetry.observe_invocation(spec=None, result=result, duration_seconds=0.01)
    exposition = observability.export_prometheus().decode("utf-8")

    assert 'outcome="DENIED"' in exposition
    assert 'error_code="CAPABILITY_UNKNOWN"' in exposition
    assert 'effect_class="unknown"' in exposition
    assert 'provider_type="unknown"' in exposition
    assert "attacker.unbounded.label.value" not in exposition
    assert "must-not-enter-telemetry" not in exposition
    assert "reader" not in exposition
    observability.close()


def test_unknown_internal_error_code_collapses_to_other() -> None:
    registry = CollectorRegistry(auto_describe=True)
    observability = Observability(registry=registry)
    telemetry = CapabilityObservability(observability)
    result = IntegrationResult(
        invocation_id=UUID("55555555-5555-5555-5555-555555555555"),
        outcome=InvocationOutcome.FAILED,
        error_code="DYNAMIC_PROVIDER_STRING_SHOULD_NOT_BECOME_A_LABEL",
    )

    telemetry.observe_invocation(spec=None, result=result, duration_seconds=-1.0)
    exposition = observability.export_prometheus().decode("utf-8")

    assert 'error_code="other"' in exposition
    assert "DYNAMIC_PROVIDER_STRING_SHOULD_NOT_BECOME_A_LABEL" not in exposition
    observability.close()


def test_outcome_unknown_has_explicit_reconciliation_counter() -> None:
    registry = CollectorRegistry(auto_describe=True)
    observability = Observability(registry=registry)
    telemetry = CapabilityObservability(observability)
    result = IntegrationResult(
        invocation_id=UUID("66666666-6666-6666-6666-666666666666"),
        outcome=InvocationOutcome.OUTCOME_UNKNOWN,
        error_code="ADAPTER_TIMEOUT",
    )

    telemetry.observe_invocation(spec=None, result=result, duration_seconds=0.2)
    exposition = observability.export_prometheus().decode("utf-8")

    assert "korpus_capability_outcome_unknown_total" in exposition
    assert 'error_code="ADAPTER_TIMEOUT"' in exposition
    observability.close()
