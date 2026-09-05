from __future__ import annotations

from contextlib import nullcontext
from uuid import UUID

from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.invoke import IntegrationResult
from korpus.application.capability_gateway.observed import ObservedCapabilityGateway
from korpus.application.capability_gateway.registry import CapabilityRegistry
from korpus.application.capability_gateway.types import (
    AdapterSpec,
    AuthorizationSpec,
    CapabilityLifecycle,
    CapabilitySpec,
    DataEgressClass,
    DataPolicySpec,
    EffectClass,
    EvidenceProfile,
    EvidenceSpec,
    IdempotencySpec,
    IntegrationRequest,
    ProviderType,
    RetrySpec,
    TimeoutSpec,
)
from korpus.domain.models import Identity


class _UnknownGateway:
    def invoke(self, *, identity: Identity, request: IntegrationRequest) -> IntegrationResult:
        del identity, request
        return IntegrationResult(
            invocation_id=UUID("33333333-3333-3333-3333-333333333333"),
            outcome=InvocationOutcome.DENIED,
            error_code="CAPABILITY_UNKNOWN",
        )


class _SuccessGateway:
    def invoke(self, *, identity: Identity, request: IntegrationRequest) -> IntegrationResult:
        del identity, request
        return IntegrationResult(
            invocation_id=UUID("44444444-4444-4444-4444-444444444444"),
            outcome=InvocationOutcome.SUCCESS,
            output={"ok": True},
            audit_record_id="audit-telemetry-1",
        )


class _Telemetry:
    def __init__(self) -> None:
        self.specs: list[object | None] = []

    def invocation_span(self, spec: object | None) -> object:
        self.specs.append(spec)
        return nullcontext()

    def observe_invocation(self, **kwargs: object) -> None:
        self.specs.append(kwargs["spec"])


def _spec() -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.telemetry.late",
        version="1.0.0",
        description="Telemetry registry provenance control.",
        provider_type=ProviderType.INTERNAL,
        adapter=AdapterSpec(adapter_id="internal.telemetry", adapter_version="1.0.0"),
        effect_class=EffectClass.READ_LOCAL,
        input_schema_id="urn:korpus:test:telemetry-input:v1",
        output_schema_id="urn:korpus:test:telemetry-output:v1",
        authorization=AuthorizationSpec(
            action="integration:telemetry:read",
            resource_mapper="telemetry_resource_v1",
        ),
        evidence=EvidenceSpec(profile=EvidenceProfile.NONE),
        timeouts=TimeoutSpec(total_ms=1000),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=False),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.NONE,
            max_request_bytes=4096,
            max_response_bytes=4096,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _request(spec: CapabilitySpec) -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id=spec.capability_id,
        capability_version=spec.version,
        input={"id": "1"},
    )


def test_late_registry_mutation_cannot_make_runtime_unknown_look_admitted_in_telemetry() -> None:
    spec = _spec()
    registry = CapabilityRegistry()
    telemetry = _Telemetry()
    wrapper = ObservedCapabilityGateway(  # type: ignore[arg-type]
        _UnknownGateway(),
        registry,
        telemetry,  # type: ignore[arg-type]
    )

    registry.register(spec)
    result = wrapper.invoke(identity=Identity(subject="reader"), request=_request(spec))

    assert result.error_code == "CAPABILITY_UNKNOWN"
    assert telemetry.specs == [None, None]


def test_prepopulated_divergent_registry_cannot_claim_runtime_capability_metadata() -> None:
    spec = _spec()
    registry = CapabilityRegistry([spec])
    telemetry = _Telemetry()
    wrapper = ObservedCapabilityGateway(  # type: ignore[arg-type]
        _UnknownGateway(),
        registry,
        telemetry,  # type: ignore[arg-type]
    )

    result = wrapper.invoke(identity=Identity(subject="reader"), request=_request(spec))

    assert result.error_code == "CAPABILITY_UNKNOWN"
    assert telemetry.specs == [None, None]


def test_success_does_not_claim_unproven_separate_registry_identity() -> None:
    spec = _spec()
    registry = CapabilityRegistry([spec])
    telemetry = _Telemetry()
    wrapper = ObservedCapabilityGateway(  # type: ignore[arg-type]
        _SuccessGateway(),
        registry,
        telemetry,  # type: ignore[arg-type]
    )

    result = wrapper.invoke(identity=Identity(subject="reader"), request=_request(spec))

    assert result.outcome is InvocationOutcome.SUCCESS
    assert telemetry.specs == [None, None]
