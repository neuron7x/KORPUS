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


def test_anchor_gap_is_measured_from_the_anchor_not_from_the_shared_outbox():
    """Черга глобальна, відставання — властивість ЦЬОГО якоря, і числа розходяться.

    Виміряно 31.08.2026: якір розгортання простояв добу на 1024 із 7223, а черга була
    ПОРОЖНЯ — її звів інший процес зі своїм шляхом якоря. Метрика показувала нуль, і
    жоден гейт не червонів. `readiness_snapshot` рахував `anchor_gap_events` увесь той
    час; на нього просто ніхто не дивився.
    """
    obs = Observability(registry=CollectorRegistry())

    obs.observe_anchor_backlog(0, 0.0, 6199)
    payload = obs.export_prometheus().decode()

    assert "korpus_audit_anchor_gap_events 6199.0" in payload
    assert "korpus_audit_anchor_pending 0.0" in payload


def test_readiness_maps_the_anchor_gap_and_not_the_queue_length():
    """Зіставлення полів знімка з метриками — саме воно й розійшлося.

    Знімок рахував обидва числа; цикл спостерігав лише довжину черги. Тут вони
    навмисно різні: черга порожня, якір відстав на 6199. Якщо зіставлення підмінити,
    метрика покаже нуль — стан, у якому система простояла добу.
    """
    obs = Observability(registry=CollectorRegistry())

    obs.observe_readiness(
        {
            "pending_anchor_events": 0,
            "oldest_pending_seconds": 0.0,
            "anchor_gap_events": 6199,
        }
    )
    payload = obs.export_prometheus().decode()

    assert "korpus_audit_anchor_gap_events 6199.0" in payload
    assert "korpus_audit_anchor_pending 0.0" in payload
