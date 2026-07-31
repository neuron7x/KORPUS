from __future__ import annotations

import json

from fastapi.testclient import TestClient


def ingest_text(
    client: TestClient,
    *,
    title: str = "Тестовий статут",
    corpus_id: str = "public",
    access_tier: int = 0,
    authority: str = "official_ua",
    text: str = "Підрозділ веде журнал перевірок. Кожен запис має містити дату та відповідальну особу.",
) -> dict[str, object]:
    response = client.post(
        "/v1/documents/ingest",
        data={
            "document_json": json.dumps(
                {
                    "canonical_title": title,
                    "corpus_id": corpus_id,
                    "issuer": "Authorized Test Authority",
                    "jurisdiction": "UA",
                    "document_type": "order",
                    "access_tier": access_tier,
                    "classification": "public" if access_tier == 0 else "restricted",
                }
            ),
            "version_json": json.dumps(
                {
                    "revision": "1.0",
                    "publication_identifier": "TEST-001",
                    "authority": authority,
                }
            ),
        },
        files={"file": ("document.txt", text.encode(), "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def approve(client: TestClient, version_id: str) -> None:
    for target in ("metadata_reviewed", "content_reviewed", "approved"):
        response = client.post(
            f"/v1/document-versions/{version_id}/review",
            json={"target": target, "note": f"verified transition to {target}"},
        )
        assert response.status_code == 200, response.text
