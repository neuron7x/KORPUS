def test_health_and_readiness(client):
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert len(ready.json()["corpus_release"]) == 16
