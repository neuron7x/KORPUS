from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from korpus.application.capability_gateway.audit import (
    InvocationOutcome,
    RepositoryCapabilityAuditSink,
    capability_policy_decision_ref,
)
from korpus.application.capability_gateway.context import (
    build_invocation_context,
    policy_context_digest,
)
from korpus.application.capability_gateway.policy import CapabilityPolicyDecision
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
    ProviderType,
    RetrySpec,
    TimeoutSpec,
)
from korpus.application.request_audit_context import (
    request_audit_context,
    reset_request_audit_context,
    set_request_audit_context,
)
from korpus.domain.models import Identity


class _AuditRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[Identity, str, str, str | None, dict[str, Any]]] = []

    def append_audit(
        self,
        actor: Identity,
        action: str,
        resource_type: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> str:
        self.calls.append((actor, action, resource_type, resource_id, payload))
        return "audit-record-1"


def _spec() -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.public.read",
        version="1.0.0",
        description="Read governed reference.",
        provider_type=ProviderType.INTERNAL,
        adapter=AdapterSpec(adapter_id="internal.reference", adapter_version="1.0.0"),
        effect_class=EffectClass.READ_LOCAL,
        input_schema_id="urn:korpus:test:input:v1",
        output_schema_id="urn:korpus:test:output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:read",
            resource_mapper="reference_public_resource_v1",
        ),
        evidence=EvidenceSpec(profile=EvidenceProfile.NONE),
        timeouts=TimeoutSpec(total_ms=1_000),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=False),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.NONE,
            max_request_bytes=16_384,
            max_response_bytes=1_048_576,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _decision() -> CapabilityPolicyDecision:
    return CapabilityPolicyDecision(
        capability_id="reference.public.read",
        capability_version="1.0.0",
        action="integration:reference:read",
        canonical_permission="answer:read",
        allowed=True,
        reason="canonical_policy_allowed",
    )


def test_policy_context_digest_is_deterministic_for_set_order() -> None:
    spec = _spec()
    first = Identity(subject="reader", roles=frozenset({"user", "instructor"}))
    second = Identity(subject="reader", roles=frozenset({"instructor", "user"}))

    assert policy_context_digest(first, spec) == policy_context_digest(second, spec)


def test_invocation_context_reuses_hashed_request_session_binding() -> None:
    identity = Identity(subject="reader", roles=frozenset({"user"}))
    request_context = request_audit_context(
        session_cookie="raw-secret-cookie",
        authorization=None,
        client_version="web-1.0",
    )
    token = set_request_audit_context(request_context)
    try:
        context = build_invocation_context(
            identity=identity,
            spec=_spec(),
            request_time=datetime(2026, 9, 4, 11, 0, tzinfo=UTC),
        )
    finally:
        reset_request_audit_context(token)

    assert context.actor.subject_id == "reader"
    assert context.actor.session_binding is not None
    assert context.actor.session_binding.startswith("session:")
    assert "raw-secret-cookie" not in context.actor.session_binding


def test_repository_audit_sink_writes_to_canonical_audit_port() -> None:
    repository = _AuditRepository()
    sink = RepositoryCapabilityAuditSink(repository)  # type: ignore[arg-type]
    identity = Identity(subject="reader", roles=frozenset({"user"}))
    context = build_invocation_context(
        identity=identity,
        spec=_spec(),
        request_time=datetime(2026, 9, 4, 11, 0, tzinfo=UTC),
    )
    decision = _decision()

    record_id = sink.append(
        identity=identity,
        spec=_spec(),
        context=context,
        decision=decision,
        logical_resource="reference:1",
        input_digest="sha256:" + "1" * 64,
        output_digest="sha256:" + "2" * 64,
        evidence_digest=None,
        idempotency_binding=None,
        provider_receipt_digest=None,
        outcome=InvocationOutcome.SUCCESS,
        error_code=None,
        started_at=context.request_time,
        ended_at=context.request_time,
    )

    assert record_id == "audit-record-1"
    actor, action, resource_type, resource_id, payload = repository.calls[0]
    assert actor == identity
    assert action == "capability.invoke"
    assert resource_type == "capability"
    assert resource_id == "reference.public.read@1.0.0"
    assert payload["policy_decision_ref"] == capability_policy_decision_ref(
        identity=identity,
        spec=_spec(),
        decision=decision,
        logical_resource="reference:1",
    )
    assert payload["outcome"] == "SUCCESS"
