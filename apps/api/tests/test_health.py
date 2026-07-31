def test_health_and_readiness_are_operational_not_information_side_channels(client):
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "audit_head": 0}
    assert "corpus_release" not in ready.text
    assert ready.headers["X-Content-Type-Options"] == "nosniff"
    assert ready.headers["Cache-Control"] == "no-store"
    assert ready.headers["X-Request-ID"]
