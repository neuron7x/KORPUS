from apps.api.tests.helpers import approve, ingest_text


def test_ingest_is_quarantined_then_approved(client):
    result = ingest_text(client)
    assert result["version"]["review_state"] == "quarantined"
    assert result["span_count"] >= 1
    approve(client, result["version"]["id"])


def test_duplicate_content_is_deduplicated(client):
    first = ingest_text(client)
    second = ingest_text(client, title="Different title")
    assert first["version"]["id"] == second["version"]["id"]
    assert second["duplicate"] is True


def test_unknown_authority_cannot_be_approved(client):
    result = ingest_text(client, authority="unknown")
    version_id = result["version"]["id"]
    for target in ("metadata_reviewed", "content_reviewed"):
        assert client.post(
            f"/v1/document-versions/{version_id}/review",
            json={"target": target, "note": "reviewed metadata and content"},
        ).status_code == 200
    response = client.post(
        f"/v1/document-versions/{version_id}/review",
        json={"target": "approved", "note": "attempted approval"},
    )
    assert response.status_code == 409
