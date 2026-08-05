from __future__ import annotations

from apps.api.tests.helpers import ingest_text


def test_near_duplicate_requires_explicit_metadata_acknowledgement(client):
    first = ingest_text(
        client,
        title="Baseline procedure",
        text=(
            "Підрозділ веде журнал перевірок щодня. "
            "Кожен запис містить дату, номер та відповідальну особу."
        ),
    )
    second = ingest_text(
        client,
        title="Copied procedure",
        text=(
            "Підрозділ веде журнал перевірок щодня. "
            "Кожен запис містить дату, номер і відповідальну особу."
        ),
    )
    version = second["version"]
    assert version["near_duplicate_of_version_id"] == first["version"]["id"]
    assert version["near_duplicate_similarity"] >= 0.90

    blocked = client.post(
        f"/v1/document-versions/{version['id']}/review",
        json={"target": "metadata_reviewed", "note": "metadata review completed"},
    )
    assert blocked.status_code == 409
    assert "near-duplicate" in blocked.text

    accepted = client.post(
        f"/v1/document-versions/{version['id']}/review",
        json={
            "target": "metadata_reviewed",
            "note": "near duplicate reviewed against the authoritative source",
            "acknowledge_near_duplicate": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["near_duplicate_acknowledged_by"] == "admin-test"
