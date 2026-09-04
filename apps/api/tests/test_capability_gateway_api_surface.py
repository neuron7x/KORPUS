from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from korpus.api.routes_integrations import build_integration_router
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.invoke import IntegrationResult
from korpus.application.capability_gateway.types import IntegrationRequest
from korpus.domain.models import Identity
from korpus.security.auth import get_identity


class _Invoker:
    def __init__(self, result: IntegrationResult) -> None:
        self.result = result
        self.calls = 0

    def invoke(self, *, identity: Identity, request: IntegrationRequest) -> IntegrationResult:
        assert identity.subject == "api-reader"
        assert request.capability_id == "reference.api.read"
        self.calls += 1
        return self.result


def _result(outcome: InvocationOutcome, error_code: str | None = None) -> IntegrationResult:
    return IntegrationResult(
        invocation_id=UUID("77777777-7777-7777-7777-777777777777"),
        outcome=outcome,
        output={"sensitive": "provider-output"},
        error_code=error_code,
    )


def _client(result: IntegrationResult) -> tuple[TestClient, _Invoker]:
    invoker = _Invoker(result)
    app = FastAPI()
    app.include_router(build_integration_router(invoker))
    app.dependency_overrides[get_identity] = lambda: Identity(subject="api-reader")
    return TestClient(app), invoker


def _request() -> dict[str, object]:
    return {
        "schema_version": "korpus.integration-request.v1",
        "capability_id": "reference.api.read",
        "capability_version": "1.0.0",
        "input": {"reference_id": "alpha"},
    }


def test_unknown_and_policy_denied_are_non_oracular_publicly() -> None:
    unknown_client, _ = _client(_result(InvocationOutcome.DENIED, "CAPABILITY_UNKNOWN"))
    denied_client, _ = _client(_result(InvocationOutcome.DENIED, "POLICY_DENIED"))

    unknown = unknown_client.post("/v1/integrations/invoke", json=_request())
    denied = denied_client.post("/v1/integrations/invoke", json=_request())

    assert unknown.status_code == 404
    assert denied.status_code == 404
    assert unknown.json()["error_code"] == "CAPABILITY_UNAVAILABLE"
    assert denied.json()["error_code"] == "CAPABILITY_UNAVAILABLE"
    assert unknown.json()["output"] is None
    assert denied.json()["output"] is None
    assert unknown.json()["evidence"] is None
    assert denied.json()["evidence"] is None


def test_failed_internal_result_never_exposes_provider_output() -> None:
    client, _ = _client(_result(InvocationOutcome.FAILED, "AUDIT_APPEND_FAILED"))

    response = client.post("/v1/integrations/invoke", json=_request())

    assert response.status_code == 503
    assert response.json()["error_code"] == "INTEGRATION_FAILED"
    assert response.json()["output"] is None
    assert response.json()["evidence"] is None


def test_outcome_unknown_forces_explicit_reconciliation_status() -> None:
    client, _ = _client(_result(InvocationOutcome.OUTCOME_UNKNOWN, "ADAPTER_TIMEOUT"))

    response = client.post("/v1/integrations/invoke", json=_request())

    assert response.status_code == 409
    assert response.json()["outcome"] == "OUTCOME_UNKNOWN"


def test_success_keeps_normal_200_envelope() -> None:
    client, invoker = _client(_result(InvocationOutcome.SUCCESS))

    response = client.post("/v1/integrations/invoke", json=_request())

    assert response.status_code == 200
    assert response.json()["output"] == {"sensitive": "provider-output"}
    assert invoker.calls == 1


def test_router_factory_is_not_activated_in_main_without_owner_config_gate() -> None:
    source = Path("apps/api/src/korpus/main.py").read_text(encoding="utf-8")

    assert "routes_integrations" not in source
    assert "build_integration_router" not in source
