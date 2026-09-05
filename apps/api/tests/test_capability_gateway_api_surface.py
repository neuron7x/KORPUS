from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

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
    values = {
        "schema_version": "korpus.integration-result.v1",
        "invocation_id": UUID("77777777-7777-7777-7777-777777777777"),
        "outcome": outcome,
        "output": {"sensitive": "provider-output"},
        "evidence": None,
        "audit_record_id": "audit-test" if outcome is InvocationOutcome.SUCCESS else None,
        "error_code": error_code,
    }
    if outcome is InvocationOutcome.SUCCESS:
        return IntegrationResult.model_validate(values)
    # Deliberately bypass the domain invariant to emulate a compromised/regressed core and
    # prove the HTTP boundary independently strips non-success data.
    return IntegrationResult.model_construct(**values)


def _unsafe_success(*, audit_record_id: str | None, error_code: str | None) -> IntegrationResult:
    return IntegrationResult.model_construct(
        schema_version="korpus.integration-result.v1",
        invocation_id=UUID("88888888-8888-8888-8888-888888888888"),
        outcome=InvocationOutcome.SUCCESS,
        output={"sensitive": "must-not-escape"},
        evidence=None,
        audit_record_id=audit_record_id,
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


def test_integration_result_rejects_non_success_payload_by_construction() -> None:
    with pytest.raises(ValidationError, match="non-success integration result"):
        IntegrationResult(
            invocation_id=UUID("77777777-7777-7777-7777-777777777777"),
            outcome=InvocationOutcome.DENIED,
            output={"sensitive": "provider-output"},
            error_code="POLICY_DENIED",
        )


def test_success_result_requires_persisted_audit_identity() -> None:
    with pytest.raises(ValidationError, match="persisted audit identity"):
        IntegrationResult(
            invocation_id=UUID("77777777-7777-7777-7777-777777777777"),
            outcome=InvocationOutcome.SUCCESS,
            output={"value": "ok"},
        )


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
    assert response.json()["output"] is None
    assert response.json()["evidence"] is None


def test_success_keeps_normal_200_envelope() -> None:
    client, invoker = _client(_result(InvocationOutcome.SUCCESS))

    response = client.post("/v1/integrations/invoke", json=_request())

    assert response.status_code == 200
    assert response.json()["output"] == {"sensitive": "provider-output"}
    assert response.json()["audit_record_id"] == "audit-test"
    assert invoker.calls == 1


def test_constructed_success_without_audit_fails_closed_at_http_boundary() -> None:
    client, invoker = _client(_unsafe_success(audit_record_id=None, error_code=None))

    response = client.post("/v1/integrations/invoke", json=_request())

    assert response.status_code == 503
    assert response.json()["outcome"] == "FAILED"
    assert response.json()["error_code"] == "INTEGRATION_FAILED"
    assert response.json()["output"] is None
    assert response.json()["evidence"] is None
    assert invoker.calls == 1


def test_constructed_success_with_error_code_fails_closed_at_http_boundary() -> None:
    client, _ = _client(_unsafe_success(audit_record_id="audit-test", error_code="ADAPTER_FAILURE"))

    response = client.post("/v1/integrations/invoke", json=_request())

    assert response.status_code == 503
    assert response.json()["outcome"] == "FAILED"
    assert response.json()["error_code"] == "INTEGRATION_FAILED"
    assert response.json()["output"] is None


def test_poisoned_internal_error_cannot_select_http_status_after_revalidation() -> None:
    client, invoker = _client(
        _unsafe_success(audit_record_id=None, error_code="CAPABILITY_UNKNOWN")
    )

    response = client.post("/v1/integrations/invoke", json=_request())

    assert response.status_code == 503
    assert response.json()["outcome"] == "FAILED"
    assert response.json()["error_code"] == "INTEGRATION_FAILED"
    assert response.json()["output"] is None
    assert response.json()["evidence"] is None
    assert invoker.calls == 1


def test_router_factory_is_not_activated_in_main_without_owner_config_gate() -> None:
    source = Path("apps/api/src/korpus/main.py").read_text(encoding="utf-8")

    assert "routes_integrations" not in source
    assert "build_integration_router" not in source
