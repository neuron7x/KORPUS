from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from pydantic import ValidationError

from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.context import build_invocation_context
from korpus.application.capability_gateway.policy import CapabilityPolicyDecision
from korpus.application.capability_gateway.result import (
    CapabilityResultEmitter,
    ExecutionMaterial,
    IntegrationResult,
    InvocationFrame,
)
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


class _Audit:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def append(self, **kwargs: object) -> str:
        del kwargs
        self.calls += 1
        return cast(str, self.value)


def _spec() -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.audit.read",
        version="1.0.0",
        description="Audit result boundary test capability.",
        provider_type=ProviderType.INTERNAL,
        adapter=AdapterSpec(adapter_id="internal.audit", adapter_version="1.0.0"),
        effect_class=EffectClass.READ_LOCAL,
        input_schema_id="urn:korpus:test:audit-input:v1",
        output_schema_id="urn:korpus:test:audit-output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:read",
            resource_mapper="reference_resource_v1",
        ),
        evidence=EvidenceSpec(profile=EvidenceProfile.NONE),
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


def _frame() -> InvocationFrame:
    identity = Identity(subject="reader", roles=frozenset({"user"}))
    spec = _spec()
    started = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
    request = IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id=spec.capability_id,
        capability_version=spec.version,
        input={"reference_id": "1"},
    )
    context = build_invocation_context(identity=identity, spec=spec, request_time=started)
    decision = CapabilityPolicyDecision(
        capability_id=spec.capability_id,
        capability_version=spec.version,
        action=spec.authorization.action,
        canonical_permission="answer:read",
        allowed=True,
        reason="canonical_policy_and_resource_allowed",
    )
    return InvocationFrame(
        identity=identity,
        request=request,
        started_at=started,
        spec=spec,
        context=context,
        decision=decision,
        logical_resource="reference:1",
    )


@pytest.mark.parametrize("audit_id", ["", "   ", "x" * 257, object()])
def test_invalid_audit_identity_never_enables_success(audit_id: object) -> None:
    audit = _Audit(audit_id)
    emitter = CapabilityResultEmitter(audit)  # type: ignore[arg-type]

    result = emitter.emit(
        _frame(),
        InvocationOutcome.SUCCESS,
        None,
        ExecutionMaterial(output={"value": "must-not-be-exposed"}),
    )

    assert audit.calls == 1
    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "AUDIT_APPEND_FAILED"
    assert result.audit_record_id is None
    assert result.output is None
    assert result.evidence is None


def test_result_model_rejects_blank_present_audit_identity() -> None:
    with pytest.raises(ValidationError, match="audit record identity must be non-blank"):
        IntegrationResult(
            invocation_id=_frame().context.invocation_id,
            outcome=InvocationOutcome.FAILED,
            audit_record_id="   ",
            error_code="INTERNAL_ERROR",
        )
