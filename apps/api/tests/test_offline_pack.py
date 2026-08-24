from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from korpus.application.offline_pack import (
    OfflinePackLimitError,
    OfflinePackService,
    canonical_json,
)
from korpus.domain.models import Identity
from korpus.infrastructure.offline_pack_signer import Ed25519OfflinePackSigner

from apps.api.tests.helpers import approve, ingest_text


def service(client: TestClient, *, max_spans: int = 100) -> OfflinePackService:
    signer = Ed25519OfflinePackSigner("offline-test-key", Ed25519PrivateKey.generate())
    return OfflinePackService(
        client.app.state.repository,
        client.app.state.policy,
        signer,
        ttl_seconds=3600,
        max_spans=max_spans,
    )


def test_export_is_fresh_policy_bound_signed_and_audited(client: TestClient) -> None:
    ingested = ingest_text(
        client, text="Офлайн доказ: резервний канал працює тільки з чинним наказом."
    )
    approve(client, ingested["version"]["id"])
    offline = service(client)
    client.app.state.offline_pack_service = offline

    response = client.post(
        "/v1/offline-pack",
        json={"corpora": ["public"]},
        headers={"X-Request-ID": "offline-export-1", "Authorization": "Bearer offline-test"},
    )
    assert response.status_code == 200
    pack = response.json()
    assert pack["schema"] == "korpus.offline-pack.v1"
    assert pack["algorithm"] == "Ed25519"
    assert pack["key_id"] == "offline-test-key"
    assert pack["corpora"] == ["public"]
    assert pack["spans"] and all(item["corpus_id"] == "public" for item in pack["spans"])
    assert pack["policy_decision_id"].startswith("pd1:")

    signed = {key: value for key, value in pack.items() if key != "signature"}
    offline.signer._private_key.public_key().verify(
        base64.b64decode(pack["signature"]), canonical_json(signed).encode("utf-8")
    )

    events = client.get("/v1/audit/events", params={"trace_id": "offline-export-1"}).json()
    exported = next(event for event in events if event["action"] == "offline_pack.exported")
    assert exported["payload"]["payload_sha256"] == pack["payload_sha256"]
    assert exported["payload"]["corpus_release"] == pack["corpus_release"]


def test_pack_never_silently_truncates_authorized_evidence(
    client: TestClient, public_identity: Identity
) -> None:
    ingested = ingest_text(client, text="Перший фрагмент. Другий фрагмент. Третій фрагмент.")
    approve(client, ingested["version"]["id"])
    offline = service(client, max_spans=0)
    with pytest.raises(OfflinePackLimitError):
        offline.export(
            public_identity,
            ["public"],
            now=datetime(2026, 8, 16, tzinfo=UTC),
        )


def test_route_is_fail_closed_when_offline_export_is_disabled(client: TestClient) -> None:
    client.app.state.offline_pack_service = None
    response = client.post("/v1/offline-pack", json={"corpora": ["public"]})
    assert response.status_code == 503
