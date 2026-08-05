from __future__ import annotations

from apps.api.tests.helpers import ingest_text


def test_low_quality_extraction_requires_explicit_reviewer_acknowledgement(client):
    result = ingest_text(
        client,
        title="Damaged OCR sample",
        text=(
            "Нормативний текст \ufffd\ufffd\ufffd "
            "із пошкодженими символами та контрольованою перевіркою."
        ),
    )
    version = result["version"]
    assert "replacement_characters" in version["extraction_quality_flags"]
    assert version["extraction_replacement_ratio"] > 0.001

    blocked = client.post(
        f"/v1/document-versions/{version['id']}/review",
        json={
            "target": "metadata_reviewed",
            "note": "metadata review without quality acknowledgement",
        },
    )
    assert blocked.status_code == 409
    assert "extraction-quality" in blocked.text

    accepted = client.post(
        f"/v1/document-versions/{version['id']}/review",
        json={
            "target": "metadata_reviewed",
            "note": "damaged extraction compared manually with the source document",
            "acknowledge_extraction_quality": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["extraction_quality_acknowledged_by"] == "admin-test"
