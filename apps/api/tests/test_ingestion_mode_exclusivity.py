"""Exactly one ingestion path is open, and the closed one says so.

`ingestion_mode` selects between the synchronous route, which parses inside the request,
and the durable queue, which stages the upload and hands it to a worker. Both sets of
routes are always mounted; the setting is what decides which of them answers.

Measured on 2026-08-28 only the open arm of each pair had been taken. The closed arm is
what keeps the two from being simultaneously live — an upload accepted synchronously in a
durable deployment bypasses the quarantine store and the malware scan behind it, and one
queued in a synchronous deployment waits for a worker nobody started.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity
from korpus.main import create_app
from korpus.security.auth import get_identity

PAYLOAD = "Наказ. Підстава: стаття 12.".encode()
DOCUMENT = json.dumps(
    {"canonical_title": "Order 41", "issuer": "Test Issuer", "corpus_id": "public"}
)
VERSION = json.dumps({"revision": "1", "authority": "official_ua"})


def _admin() -> Identity:
    return Identity(
        subject="mode-admin",
        roles=frozenset({"admin", "curator", "reviewer", "user", "auditor"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )


def _settings(tmp_path: Path, mode: str) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'mode.db'}",
        object_root=tmp_path / "objects",
        quarantine_object_root=tmp_path / "quarantine",
        audit_anchor_path=tmp_path / "anchor.json",
        audit_hmac_key="ingestion-mode-audit-key",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        ingestion_mode=mode,
        malware_scan_mode="disabled",
        parser_sandbox_enabled=False,
        max_upload_bytes=1024 * 1024,
    )


def _client(tmp_path: Path, mode: str) -> TestClient:
    app = create_app(_settings(tmp_path, mode))
    app.dependency_overrides[get_identity] = _admin
    return TestClient(app)


def _files() -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("order.txt", PAYLOAD, "text/plain")}


def test_the_synchronous_route_is_closed_in_a_durable_deployment(tmp_path: Path) -> None:
    """Answering here would skip the quarantine store the durable path exists to use."""
    with _client(tmp_path, "durable_async") as client:
        response = client.post(
            "/v1/documents/ingest",
            data={"document_json": DOCUMENT, "version_json": VERSION},
            files=_files(),
        )
    assert response.status_code == 409, response.text
    assert "durable ingestion jobs" in response.text


def test_the_durable_routes_are_closed_in_a_synchronous_deployment(tmp_path: Path) -> None:
    """A queued job in a deployment with no worker is an upload that never lands."""
    with _client(tmp_path, "synchronous") as client:
        queued = client.post(
            "/v1/ingestion-jobs/documents",
            data={"document_json": DOCUMENT, "version_json": VERSION},
            files=_files(),
        )
        assert queued.status_code == 409, queued.text
        assert "durable ingestion is disabled" in queued.text

        ingested = client.post(
            "/v1/documents/ingest",
            data={"document_json": DOCUMENT, "version_json": VERSION},
            files=_files(),
        )
        assert ingested.status_code in {200, 201}, ingested.text
        document_id = ingested.json()["document"]["id"]

        version_job = client.post(
            f"/v1/documents/{document_id}/ingestion-jobs",
            data={"version_json": json.dumps({"revision": "2", "authority": "official_ua"})},
            files=_files(),
        )
        assert version_job.status_code == 409, version_job.text
        assert "durable ingestion is disabled" in version_job.text


def test_an_unknown_job_id_is_not_found_rather_than_an_error(tmp_path: Path) -> None:
    """Absent and belonging-to-someone-else answer the same way, on purpose.

    Distinguishing them would make the endpoint an oracle for job ids created by other
    subjects.
    """
    with _client(tmp_path, "durable_async") as client:
        response = client.get(f"/v1/ingestion-jobs/{uuid4()}")
    assert response.status_code == 404
    assert "ingestion job not found" in response.text


@pytest.mark.parametrize("mode", ["synchronous", "durable_async"])
def test_each_mode_opens_exactly_one_of_the_two_paths(tmp_path: Path, mode: str) -> None:
    """The dual, stated as the property rather than as two separate cases."""
    with _client(tmp_path, mode) as client:
        synchronous = client.post(
            "/v1/documents/ingest",
            data={"document_json": DOCUMENT, "version_json": VERSION},
            files=_files(),
        )
        durable = client.post(
            "/v1/ingestion-jobs/documents",
            data={"document_json": DOCUMENT, "version_json": VERSION},
            files=_files(),
        )
    open_paths = [
        name
        for name, response in (("synchronous", synchronous), ("durable", durable))
        if response.status_code != 409
    ]
    assert open_paths == ([mode.replace("_async", "")] if mode != "durable_async" else ["durable"])
