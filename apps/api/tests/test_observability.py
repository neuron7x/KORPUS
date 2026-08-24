from korpus.infrastructure.observability import Observability
from prometheus_client import CollectorRegistry


def test_metrics_are_low_cardinality_and_exported():
    obs = Observability(registry=CollectorRegistry())
    obs.observe_http("GET", "/health", 200, 0.01)
    obs.observe_answer("answered", "extractive_claims_passed_calibrated_gates", "standard")
    payload = obs.export_prometheus().decode()
    assert 'route="/health"' in payload
    assert "query=" not in payload
    assert "subject=" not in payload
    assert "korpus_answers_total" in payload


def test_metrics_endpoint_is_available(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "korpus_http_requests_total" in response.text


def test_admission_gauge_returns_to_zero_after_answer(client):
    response = client.post("/v1/answers", json={"text": "невідоме питання"})
    assert response.status_code == 200
    payload = client.get("/metrics").text
    assert "korpus_admission_active 0.0" in payload


def test_security_metrics_reject_unbounded_or_invented_labels():
    import pytest

    obs = Observability(registry=CollectorRegistry())
    obs.observe_security_event("authorization_denied")
    with pytest.raises(ValueError):
        obs.observe_security_event("subject:alice")
    payload = obs.export_prometheus().decode()
    assert 'event="authorization_denied"' in payload
    assert "alice" not in payload
