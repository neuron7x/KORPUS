from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from korpus.application.capability_gateway.adapters import AdapterExecutionFailed
from korpus.application.capability_gateway.evidence import validate_evidence
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
from korpus.infrastructure.integrations.http import GovernedHttpReadAdapter, HttpReadPlan


def _spec(
    *,
    effect: EffectClass = EffectClass.READ_REMOTE,
    evidence: EvidenceProfile = EvidenceProfile.PROVIDER_PROVENANCE,
    max_response_bytes: int = 4096,
) -> CapabilitySpec:
    effectful = effect in {
        EffectClass.WRITE_REMOTE,
        EffectClass.TRANSACTIONAL_SIDE_EFFECT,
        EffectClass.PRIVILEGED_ADMIN,
    }
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.remote.read",
        version="1.0.0",
        description="Governed remote reference read.",
        provider_type=ProviderType.HTTP,
        adapter=AdapterSpec(adapter_id="http.reference", adapter_version="1.0.0"),
        effect_class=effect,
        input_schema_id="urn:korpus:test:http-input:v1",
        output_schema_id="urn:korpus:test:http-output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:read",
            resource_mapper="reference_resource_v1",
            requires_explicit_effect_authorization=effectful,
        ),
        evidence=EvidenceSpec(
            profile=evidence,
            freshness_seconds=300,
            bind_output_digest=True,
        ),
        timeouts=TimeoutSpec(total_ms=500),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=effectful),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.PUBLIC_ONLY,
            max_request_bytes=4096,
            max_response_bytes=max_response_bytes,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _request() -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.remote.read",
        capability_version="1.0.0",
        input={"reference_id": "alpha"},
    )


def _context() -> InvocationContext:
    return InvocationContext(
        schema_version="korpus.invocation-context.v1",
        invocation_id=UUID("22222222-2222-2222-2222-222222222222"),
        actor=InvocationActor(actor_type=ActorType.USER, subject_id="reader"),
        request_time=datetime(2026, 9, 4, 8, 0, tzinfo=UTC),
        service_release="0.9.7",
        policy_context_digest="sha256:" + "1" * 64,
    )


def _plan(payload: dict[str, object], resource: str) -> HttpReadPlan:
    del resource
    return HttpReadPlan(path="v1/reference", query=(("id", str(payload["reference_id"])),))


def test_http_adapter_keeps_exact_origin_and_emits_valid_provenance() -> None:
    seen: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"value": "ok"}, request=request)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        adapter = GovernedHttpReadAdapter(
            client=client,
            base_url="https://provider.example/api",
            plan_builder=_plan,
            headers={"Authorization": "Bearer server-owned"},
        )
        result = adapter.execute(
            spec=_spec(),
            request=_request(),
            context=_context(),
            logical_resource="reference/alpha",
        )

    assert result.output == {"value": "ok"}
    assert len(seen) == 1
    assert str(seen[0].url) == "https://provider.example/api/v1/reference?id=alpha"
    assert result.evidence is not None
    assert result.evidence.provenance.source_refs == [
        "https://provider.example/api/v1/reference"
    ]
    assert result.evidence.provenance.provider_identity == "https://provider.example"
    validate_evidence(
        spec=_spec(),
        context=_context(),
        output=result.output,
        evidence=result.evidence,
        evaluated_at=datetime.now(UTC),
    )


def test_http_adapter_rejects_percent_encoded_path_traversal_before_network() -> None:
    calls = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"unexpected": True}, request=request)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        adapter = GovernedHttpReadAdapter(
            client=client,
            base_url="https://provider.example/api",
            plan_builder=lambda payload, resource: HttpReadPlan(path="%2e%2e/admin"),
        )
        with pytest.raises(AdapterExecutionFailed, match="request plan rejected"):
            adapter.execute(
                spec=_spec(),
                request=_request(),
                context=_context(),
                logical_resource="reference/alpha",
            )

    assert calls == 0


def test_http_adapter_refuses_redirects() -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "https://evil.example/collect"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        adapter = GovernedHttpReadAdapter(
            client=client, base_url="https://provider.example/api", plan_builder=_plan
        )
        with pytest.raises(AdapterExecutionFailed, match="redirect refused"):
            adapter.execute(
                spec=_spec(),
                request=_request(),
                context=_context(),
                logical_resource="reference/alpha",
            )


def test_http_adapter_bounds_decompressed_response_bytes() -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"value":"too-large"}',
            headers={"content-type": "application/json"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        adapter = GovernedHttpReadAdapter(
            client=client, base_url="https://provider.example/api", plan_builder=_plan
        )
        with pytest.raises(AdapterExecutionFailed, match="exceeds configured maximum"):
            adapter.execute(
                spec=_spec(max_response_bytes=8),
                request=_request(),
                context=_context(),
                logical_resource="reference/alpha",
            )


def test_http_adapter_normalizes_transport_failure_without_provider_detail() -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("secret-provider-timeout-detail", request=request)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        adapter = GovernedHttpReadAdapter(
            client=client, base_url="https://provider.example/api", plan_builder=_plan
        )
        with pytest.raises(AdapterExecutionFailed, match="HTTP provider unavailable") as exc_info:
            adapter.execute(
                spec=_spec(),
                request=_request(),
                context=_context(),
                logical_resource="reference/alpha",
            )

    assert "secret-provider-timeout-detail" not in str(exc_info.value)


def test_http_adapter_refuses_effectful_and_factual_profiles_before_network() -> None:
    calls = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"unexpected": True}, request=request)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        adapter = GovernedHttpReadAdapter(
            client=client, base_url="https://provider.example/api", plan_builder=_plan
        )
        with pytest.raises(AdapterExecutionFailed, match="read-only"):
            adapter.execute(
                spec=_spec(effect=EffectClass.WRITE_REMOTE),
                request=_request(),
                context=_context(),
                logical_resource="reference/alpha",
            )
        with pytest.raises(AdapterExecutionFailed, match="cannot manufacture"):
            adapter.execute(
                spec=_spec(evidence=EvidenceProfile.FACTUAL_EVIDENCE),
                request=_request(),
                context=_context(),
                logical_resource="reference/alpha",
            )

    assert calls == 0


def test_http_adapter_rejects_routing_and_framing_headers_at_composition() -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        with pytest.raises(ValueError, match="header is forbidden"):
            GovernedHttpReadAdapter(
                client=client,
                base_url="https://provider.example/api",
                plan_builder=_plan,
                headers={"Host": "evil.example"},
            )
