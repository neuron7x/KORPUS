from sqlalchemy import text

from apps.api.tests.helpers import approve, ingest_text


def test_audit_chain_verifies(client):
    result = ingest_text(client)
    approve(client, result["version"]["id"])
    client.post("/v1/answers", json={"text": "Що має містити запис?"})
    response = client.get("/v1/audit/verify")
    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["event_count"] >= 5


def test_audit_chain_detects_tampering(client):
    ingest_text(client)
    repository = client.app.state.repository
    with repository.engine.begin() as connection:
        connection.execute(text("UPDATE audit_events SET payload_json='{}' WHERE sequence=1"))
    response = client.get("/v1/audit/verify")
    assert response.json()["valid"] is False
    assert response.json()["first_invalid_sequence"] == 1
