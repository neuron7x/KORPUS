from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from korpus.api.routes_integrations import build_integration_router
from korpus.domain.models import Identity
from korpus.security.auth import get_identity


class _InvalidInvoker:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, **kwargs: object) -> object:
        del kwargs
        self.calls += 1
        return {"outcome": "SUCCESS", "output": {"sensitive": "must-not-escape"}}


def test_invalid_invoker_runtime_type_fails_closed_at_http_boundary() -> None:
    invoker = _InvalidInvoker()
    app = FastAPI()
    app.include_router(build_integration_router(invoker))  # type: ignore[arg-type]
    app.dependency_overrides[get_identity] = lambda: Identity(subject="api-reader")
    client = TestClient(app)

    response = client.post(
        "/v1/integrations/invoke",
        json={
            "schema_version": "korpus.integration-request.v1",
            "capability_id": "reference.api.read",
            "capability_version": "1.0.0",
            "input": {"reference_id": "alpha"},
        },
    )

    assert invoker.calls == 1
    assert response.status_code == 503
    assert response.json()["outcome"] == "FAILED"
    assert response.json()["error_code"] == "INTEGRATION_FAILED"
    assert response.json()["output"] is None
    assert response.json()["evidence"] is None
