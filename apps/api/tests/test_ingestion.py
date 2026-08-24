from __future__ import annotations

import json

import pytest

from apps.api.tests.helpers import approve, ingest_text


def test_ingest_is_quarantined_then_approved_with_provenance(client):
    result = ingest_text(client)
    assert result["version"]["review_state"] == "quarantined"
    assert result["version"]["is_current"] is False
    assert result["span_count"] >= 1
    approved = approve(client, result["version"]["id"])
    assert approved["review_state"] == "approved"
    assert approved["is_current"] is True
    assert approved["approved_by"] == "admin-test"
    assert approved["state_version"] == 3


def test_duplicate_content_is_deduplicated_only_inside_same_corpus(client, admin_identity):
    first = ingest_text(client)
    second = ingest_text(client, title="Different title")
    assert first["version"]["id"] == second["version"]["id"]
    assert second["duplicate"] is True

    restricted = ingest_text(
        client,
        title="Same bytes restricted",
        corpus_id="restricted-demo",
        access_tier=3,
        text=(
            "Підрозділ веде журнал перевірок. Кожен запис має містити дату та відповідальну особу."
        ),
    )
    assert restricted["version"]["id"] != first["version"]["id"]
    assert restricted["duplicate"] is False


def test_unknown_authority_cannot_be_approved(client):
    result = ingest_text(client, authority="unknown")
    version_id = result["version"]["id"]
    for target in ("metadata_reviewed", "content_reviewed"):
        response = client.post(
            f"/v1/document-versions/{version_id}/review",
            json={"target": target, "note": "independent metadata and content review completed"},
        )
        assert response.status_code == 200
    response = client.post(
        f"/v1/document-versions/{version_id}/review",
        json={
            "target": "approved",
            "note": "independent approval attempted with unknown authority",
        },
    )
    assert response.status_code == 409


def test_classification_cannot_be_weaker_than_access_tier(client):
    response = client.post(
        "/v1/documents/ingest",
        data={
            "document_json": json.dumps(
                {
                    "canonical_title": "Misclassified",
                    "corpus_id": "public",
                    "issuer": "Issuer",
                    "document_type": "order",
                    "access_tier": 0,
                    "classification": "restricted",
                }
            ),
            "version_json": json.dumps({"revision": "1", "authority": "official_ua"}),
        },
        files={"file": ("x.txt", b"payload", "text/plain")},
    )
    assert response.status_code == 422


def test_upload_size_limit_is_enforced_before_extraction(client):
    response = client.post(
        "/v1/documents/ingest",
        data={
            "document_json": json.dumps(
                {
                    "canonical_title": "Oversized",
                    "corpus_id": "public",
                    "issuer": "Issuer",
                    "document_type": "order",
                }
            ),
            "version_json": json.dumps({"revision": "1", "authority": "official_ua"}),
        },
        files={"file": ("x.txt", b"x" * (1024 * 1024 + 1), "text/plain")},
    )
    assert response.status_code == 422
    assert "size limit" in response.text


def test_database_bundle_and_audit_roll_back_together(client, monkeypatch):
    repository = client.app.state.repository
    original = repository._append_audit_in_connection

    def fail(*args, **kwargs):
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(repository, "_append_audit_in_connection", fail)
    with pytest.raises(RuntimeError, match="forced audit failure"):
        ingest_text(client, title="Atomic rollback", text="ATOMIC-ROLLBACK-MARKER")
    monkeypatch.setattr(repository, "_append_audit_in_connection", original)
    assert repository.list_documents(client.identity_provider.current) == []
    assert repository.verify_audit().event_count == 0
