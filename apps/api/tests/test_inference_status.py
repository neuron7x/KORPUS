from __future__ import annotations

from fastapi.testclient import TestClient


def test_inference_status_is_fail_closed_by_default(client: TestClient) -> None:
    response = client.get("/v1/inference/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is False
    assert body["provider"] == "none"
    assert body["answer_authority"] == "extractive_evidence"
    assert body["failure_mode"] == "extractive_fallback"
    assert body["max_input_bytes"] == 65_536
    assert body["max_response_bytes"] == 262_144
    assert body["max_query_variants"] == 4
    assert body["max_query_variant_chars"] == 120
    assert body["max_composition_sentences"] == 4
    assert body["openai_store"] is None
    assert "api_key" not in body
    assert "base_url" not in body
