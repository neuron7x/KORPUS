import json

from apps.api.tests.helpers import approve, ingest_text


def test_new_approved_version_supersedes_old_version_in_retrieval(client):
    first = ingest_text(client, text="OLD-MARKER журнал містить старий порядок перевірки.")
    approve(client, first["version"]["id"])
    second_response = client.post(
        f'/v1/documents/{first["document"]["id"]}/versions/ingest',
        data={"version_json": json.dumps({
            "revision": "2.0",
            "authority": "official_ua",
            "supersedes_version_id": first["version"]["id"],
        })},
        files={"file": ("v2.txt", b"NEW-MARKER journal uses the current verification procedure.", "text/plain")},
    )
    assert second_response.status_code == 201, second_response.text
    second = second_response.json()
    approve(client, second["version"]["id"])

    old_answer = client.post("/v1/answers", json={"text": "OLD-MARKER"}).json()
    new_answer = client.post("/v1/answers", json={"text": "NEW-MARKER current verification"}).json()
    assert old_answer["status"] == "insufficient_evidence"
    assert new_answer["status"] == "answered"
    assert all(citation["version_id"] == second["version"]["id"] for citation in new_answer["citations"])


def test_supersedes_must_reference_same_document(client):
    first = ingest_text(client, title="One", text="Document one unique content.")
    second = ingest_text(client, title="Two", text="Document two unique content.")
    response = client.post(
        f'/v1/documents/{second["document"]["id"]}/versions/ingest',
        data={"version_json": json.dumps({
            "revision": "2",
            "authority": "official_ua",
            "supersedes_version_id": first["version"]["id"],
        })},
        files={"file": ("v2.txt", b"Third unique version content.", "text/plain")},
    )
    assert response.status_code == 422
