"""Проєкція наслідку виклику в код HTTP.

Кожен наслідок мусить мати ВЛАСНИЙ код: клієнт, що бачить один код на всі відмови,
не може відрізнити «не можна» від «спробуй пізніше» і ретраїть те, що ретраю не підлягає.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from korpus.api.routes_integrations import build_integration_router
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.result import IntegrationResult
from korpus.domain.models import Identity
from korpus.security.auth import get_identity


class _FixedInvoker:
    def __init__(self, result: IntegrationResult) -> None:
        self._result = result
        self.calls = 0

    def invoke(self, **kwargs: object) -> IntegrationResult:
        del kwargs
        self.calls += 1
        return self._result


def _client(result: IntegrationResult) -> tuple[TestClient, _FixedInvoker]:
    invoker = _FixedInvoker(result)
    app = FastAPI()
    app.include_router(build_integration_router(invoker))  # type: ignore[arg-type]
    app.dependency_overrides[get_identity] = lambda: Identity(subject="api-reader")
    return TestClient(app), invoker


def _post(client: TestClient) -> object:
    return client.post(
        "/v1/integrations/invoke",
        json={
            "schema_version": "korpus.integration-request.v1",
            "capability_id": "reference.api.read",
            "capability_version": "1.0.0",
            "input": {"reference_id": "alpha"},
        },
    )


@pytest.mark.parametrize(
    ("outcome", "error_code", "expected_status"),
    [
        (InvocationOutcome.DENIED, "EGRESS_DENIED", 403),
        (InvocationOutcome.REJECTED, "SCHEMA_REJECTED", 422),
        (InvocationOutcome.FAILED, "ADAPTER_FAILED", 503),
        (InvocationOutcome.ABSTAINED, "IDEMPOTENCY_CONFLICT", 409),
        (InvocationOutcome.OUTCOME_UNKNOWN, "PROVIDER_STATE_UNKNOWN", 409),
    ],
)
def test_each_non_success_outcome_carries_its_own_status(
    outcome: InvocationOutcome,
    error_code: str,
    expected_status: int,
) -> None:
    result = IntegrationResult(invocation_id=uuid4(), outcome=outcome, error_code=error_code)
    client, invoker = _client(result)

    response = _post(client)

    assert invoker.calls == 1
    assert response.status_code == expected_status
    assert response.json()["outcome"] == outcome.value
    assert response.json()["output"] is None
    assert response.json()["evidence"] is None


@pytest.mark.parametrize(
    "error_code", ["CAPABILITY_UNKNOWN", "CAPABILITY_DISABLED", "POLICY_DENIED"]
)
def test_preauth_denial_hides_existence_regardless_of_outcome(error_code: str) -> None:
    """404 стоїть ПЕРЕД відображенням наслідку: 403 сам по собі підтвердив би спроможність."""
    result = IntegrationResult(
        invocation_id=uuid4(),
        outcome=InvocationOutcome.DENIED,
        error_code=error_code,
    )
    client, _ = _client(result)

    response = _post(client)

    assert response.status_code == 404
    assert response.json()["error_code"] == "CAPABILITY_UNAVAILABLE"


def test_successful_invocation_keeps_its_audit_identity_and_status() -> None:
    """Негативний контроль: відображення не чіпає успіх."""
    result = IntegrationResult(
        invocation_id=uuid4(),
        outcome=InvocationOutcome.SUCCESS,
        output={"reference_id": "alpha"},
        audit_record_id="audit-1",
    )
    client, _ = _client(result)

    response = _post(client)

    assert response.status_code == 200
    assert response.json()["outcome"] == "SUCCESS"
    assert response.json()["audit_record_id"] == "audit-1"
