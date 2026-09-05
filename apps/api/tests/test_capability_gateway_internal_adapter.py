from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from korpus.application.capability_gateway.adapters import AdapterExecutionFailed, AdapterRegistry
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.invoke import CapabilityGateway
from korpus.application.capability_gateway.policy import CapabilityPolicyBridge
from korpus.application.capability_gateway.registry import CapabilityRegistry
from korpus.application.capability_gateway.types import (
    ActorType,
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
    InvocationActor,
    InvocationContext,
    ProviderType,
    RetrySpec,
    TimeoutSpec,
)
from korpus.application.capability_gateway.validation import ExactSchemaRegistry
from korpus.application.policy import PolicyEngine
from korpus.domain.models import Identity
from korpus.infrastructure.integrations.internal import InternalFunctionAdapter


def _spec(*, evidence: EvidenceProfile = EvidenceProfile.EXECUTION_ONLY) -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.internal.read",
        version="1.0.0",
        description="Deterministic internal reference read.",
        provider_type=ProviderType.INTERNAL,
        adapter=AdapterSpec(adapter_id="internal.reference", adapter_version="1.0.0"),
        effect_class=EffectClass.READ_LOCAL,
        input_schema_id="urn:korpus:test:internal-input:v1",
        output_schema_id="urn:korpus:test:internal-output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:read",
            resource_mapper="reference_resource_v1",
        ),
        evidence=EvidenceSpec(profile=evidence, bind_output_digest=True),
        timeouts=TimeoutSpec(total_ms=100),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=False),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.NONE,
            max_request_bytes=4096,
            max_response_bytes=4096,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _request() -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.internal.read",
        capability_version="1.0.0",
        input={"reference_id": "alpha"},
    )


def _context() -> InvocationContext:
    return InvocationContext(
        schema_version="korpus.invocation-context.v1",
        invocation_id=UUID("11111111-1111-1111-1111-111111111111"),
        actor=InvocationActor(actor_type=ActorType.USER, subject_id="reader"),
        request_time=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
        service_release="0.9.7",
        policy_context_digest="sha256:" + "0" * 64,
    )


class _NoEffects:
    def reserve(self, **kwargs: object) -> object:
        del kwargs
        raise AssertionError("READ_LOCAL must not reserve side effects")

    def transition(self, **kwargs: object) -> object:
        del kwargs
        raise AssertionError("READ_LOCAL must not transition side effects")


class _NoEgress:
    def check(self, **kwargs: object) -> None:
        del kwargs


class _NoEffectAuthorization:
    def authorize(self, **kwargs: object) -> bool:
        del kwargs
        raise AssertionError("READ_LOCAL must not request effect authorization")


class _Audit:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def append(self, **kwargs: object) -> str:
        self.calls.append(dict(kwargs))
        return "audit-internal-1"


def test_internal_adapter_is_deterministic_for_fixed_context() -> None:
    adapter = InternalFunctionAdapter(
        lambda payload, resource: {"id": payload["reference_id"], "resource": resource}
    )
    first = adapter.execute(
        spec=_spec(), request=_request(), context=_context(), logical_resource="reference/alpha"
    )
    second = adapter.execute(
        spec=_spec(), request=_request(), context=_context(), logical_resource="reference/alpha"
    )

    assert first == second
    assert first.evidence is not None
    assert first.evidence.reproducible is True
    assert first.evidence.binding.output_digest == second.evidence.binding.output_digest


def test_internal_adapter_refuses_authority_profiles_it_cannot_prove() -> None:
    adapter = InternalFunctionAdapter(lambda payload, resource: {"ok": True})

    with pytest.raises(AdapterExecutionFailed):
        adapter.execute(
            spec=_spec(evidence=EvidenceProfile.FACTUAL_EVIDENCE),
            request=_request(),
            context=_context(),
            logical_resource="reference/alpha",
        )


def test_internal_adapter_normalizes_handler_failure() -> None:
    def fail(payload: object, resource: str) -> object:
        del payload, resource
        raise ValueError("sensitive internal detail")

    adapter = InternalFunctionAdapter(fail)
    with pytest.raises(AdapterExecutionFailed, match="internal handler failed"):
        adapter.execute(
            spec=_spec(), request=_request(), context=_context(), logical_resource="reference/alpha"
        )


def test_real_internal_adapter_completes_full_gateway_flow() -> None:
    spec = _spec()
    registry = CapabilityRegistry([spec])
    adapters = AdapterRegistry()
    adapters.register(
        "internal.reference",
        "1.0.0",
        InternalFunctionAdapter(
            lambda payload, resource: {"id": payload["reference_id"], "resource": resource}
        ),
    )
    schemas = ExactSchemaRegistry(
        {
            "urn:korpus:test:internal-input:v1": lambda value: None,
            "urn:korpus:test:internal-output:v1": lambda value: None,
        }
    )
    audit = _Audit()
    gateway = CapabilityGateway(
        registry=registry,
        policy=CapabilityPolicyBridge(
            PolicyEngine(),
            action_permissions={"integration:reference:read": "answer:read"},
            resource_authorizers={
                "reference_resource_v1": (
                    lambda identity, declared, resource: resource == "reference/alpha"
                )
            },
        ),
        adapters=adapters,
        schemas=schemas,
        resource_mappers={
            "reference_resource_v1": lambda identity, declared, request: (
                f"reference/{request.input['reference_id']}"
            )
        },
        egress=_NoEgress(),
        effect_authorizer=_NoEffectAuthorization(),
        effects=_NoEffects(),
        audit=audit,
    )

    result = gateway.invoke(
        identity=Identity(subject="reader", roles=frozenset({"user"})),
        request=_request(),
    )

    assert result.outcome is InvocationOutcome.SUCCESS
    assert result.output == {"id": "alpha", "resource": "reference/alpha"}
    assert result.evidence is not None
    assert result.audit_record_id == "audit-internal-1"
    assert len(audit.calls) == 1
    assert audit.calls[0]["outcome"] is InvocationOutcome.SUCCESS
