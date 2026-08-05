from korpus.domain.models import AccessTier, Identity

from apps.api.tests.conftest import set_identity


def test_document_and_audit_routes_are_denied_without_permissions(client):
    set_identity(
        client,
        Identity(
            subject="nobody",
            roles=frozenset(),
            clearance=AccessTier.PUBLIC,
            corpora=frozenset({"public"}),
        ),
    )
    assert client.get("/v1/documents").status_code == 403
    assert client.get("/v1/audit/verify").status_code == 403


def test_ingest_rejects_empty_file(client):
    import json

    response = client.post(
        "/v1/documents/ingest",
        data={
            "document_json": json.dumps(
                {
                    "canonical_title": "Empty test",
                    "corpus_id": "public",
                    "issuer": "Issuer",
                    "jurisdiction": "UA",
                    "document_type": "order",
                    "access_tier": 0,
                    "classification": "public",
                }
            ),
            "version_json": json.dumps({"revision": "1", "authority": "official_ua"}),
        },
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert response.status_code == 422
