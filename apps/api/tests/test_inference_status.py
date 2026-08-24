from __future__ import annotations

from fastapi.testclient import TestClient


def test_inference_status_is_fail_closed_by_default(client: TestClient) -> None:
    response = client.get("/v1/inference/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is False
    assert body["provider"] == "none"
    assert body["answer_authority"] == "extractive_evidence"
    assert body["openai_store"] is None
    assert "api_key" not in body
    assert "base_url" not in body
