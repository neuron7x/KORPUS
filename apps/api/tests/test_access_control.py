from apps.api.tests.helpers import approve, ingest_text


def test_public_identity_cannot_request_restricted_corpus(client, public_identity):
    client.app.state.identity_override = public_identity
    response = client.post(
        "/v1/answers",
        json={"text": "секретний порядок", "corpus_ids": ["restricted-demo"]},
    )
    assert response.status_code == 403


def test_restricted_document_does_not_leak_to_public_identity(client, admin_identity, public_identity):
    client.app.state.identity_override = admin_identity
    result = ingest_text(
        client,
        title="Restricted procedure",
        corpus_id="restricted-demo",
        access_tier=3,
        text="Секретний маркер ALPHA-RESTRICTED не можна показувати публічним користувачам.",
    )
    approve(client, result["version"]["id"])
    client.app.state.identity_override = public_identity
    response = client.post("/v1/answers", json={"text": "ALPHA-RESTRICTED"})
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert "ALPHA-RESTRICTED" not in body["text"]
    assert body["citations"] == []
