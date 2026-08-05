def test_health_and_readiness_are_operational_not_information_side_channels(client):
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready")
    assert ready.status_code == 200
    # `telemetry` is a bare status word: DISABLED, ACTIVE or REQUESTED_NOT_ACTIVE. The
    # third distinguishes "no tracing" from "tracing configured and going nowhere",
    # which an operator reading otlp_endpoint in the config cannot otherwise tell. The
    # endpoint itself stays out — this response is unauthenticated.
    assert ready.json() == {"status": "ready", "audit_head": 0, "telemetry": "DISABLED"}
    assert "http" not in ready.text.lower().replace("x-content-type-options", "")
    assert "corpus_release" not in ready.text
    assert ready.headers["X-Content-Type-Options"] == "nosniff"
    assert ready.headers["Cache-Control"] == "no-store"
    assert ready.headers["X-Request-ID"]
