from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.ingestion_jobs import IngestionWorker
from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity, IngestionJobState
from korpus.main import create_app
from korpus.security.auth import get_identity


def _admin() -> Identity:
    return Identity(
        subject="job-admin",
        roles=frozenset({"admin", "curator", "reviewer", "user", "auditor"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'jobs.db'}",
        object_root=tmp_path / "objects",
        quarantine_object_root=tmp_path / "quarantine",
        audit_anchor_path=tmp_path / "anchor.json",
        audit_hmac_key="durable-job-audit-key",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        ingestion_mode="durable_async",
        malware_scan_mode="disabled",
        parser_sandbox_enabled=False,
        max_upload_bytes=1024 * 1024,
        upload_spool_threshold_bytes=64 * 1024,
        min_retrieval_score=0.08,
        min_query_coverage=0.15,
        min_support_score=0.08,
    )


def _worker(client: TestClient, worker_id: str = "worker-1") -> IngestionWorker:
    service = IngestionService(
        client.app.state.repository,
        client.app.state.object_store,
        client.app.state.policy,
        ExtractionSettings(ocr_enabled=False, ocr_languages="ukr"),
    )
    return IngestionWorker(
        client.app.state.ingestion_jobs,
        client.app.state.quarantine_store,
        service,
        client.app.state.repository,
        worker_id=worker_id,
        lease_seconds=30,
    )


def test_durable_job_submission_is_non_parsing_and_worker_completes(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    app.dependency_overrides[get_identity] = _admin
    payload = "Кожен запис має містити дату та відповідальну особу.".encode("utf-8")
    with TestClient(app) as client:
        response = client.post(
            "/v1/ingestion-jobs/documents",
            data={
                "document_json": json.dumps({
                    "canonical_title": "Durable job document",
                    "corpus_id": "public",
                    "issuer": "Authorized Test Authority",
                    "jurisdiction": "UA",
                    "document_type": "order",
                    "access_tier": 0,
                    "classification": "public",
                }),
                "version_json": json.dumps({"revision": "1", "authority": "official_ua"}),
            },
            files={"file": ("document.txt", payload, "text/plain")},
        )
        assert response.status_code == 202, response.text
        submitted = response.json()
        assert submitted["state"] == "queued"
        assert client.app.state.quarantine_store.exists(submitted["staging_object_key"])
        assert client.get(f"/v1/ingestion-jobs/{submitted['id']}").json()["state"] == "queued"

        execution = _worker(client).run_once()
        assert execution.claimed is True
        assert execution.job is not None
        assert execution.job.state is IngestionJobState.SUCCEEDED
        assert execution.job.result is not None
        assert execution.job.result.span_count > 0
        refreshed = client.get(f"/v1/ingestion-jobs/{submitted['id']}").json()
        assert refreshed["state"] == "succeeded"
        assert refreshed["result"]["document"]["canonical_title"] == "Durable job document"


def test_synchronous_endpoint_is_disabled_in_durable_mode(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    app.dependency_overrides[get_identity] = _admin
    with TestClient(app) as client:
        response = client.post(
            "/v1/documents/ingest",
            data={
                "document_json": json.dumps({
                    "canonical_title": "Rejected synchronous ingest",
                    "corpus_id": "public",
                    "issuer": "Authority",
                }),
                "version_json": json.dumps({"revision": "1"}),
            },
            files={"file": ("document.txt", b"text", "text/plain")},
        )
        assert response.status_code == 409


def test_job_failure_is_dead_lettered_for_deterministic_parser_error(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    app.dependency_overrides[get_identity] = _admin
    with TestClient(app) as client:
        response = client.post(
            "/v1/ingestion-jobs/documents",
            data={
                "document_json": json.dumps({
                    "canonical_title": "Bad type",
                    "corpus_id": "public",
                    "issuer": "Authority",
                }),
                "version_json": json.dumps({"revision": "1"}),
            },
            files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
        )
        assert response.status_code == 202
        execution = _worker(client).run_once()
        assert execution.job is not None
        assert execution.job.state is IngestionJobState.DEAD_LETTER
        assert execution.job.error_code == "ValueError"


def test_job_lease_is_exclusive(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    app.dependency_overrides[get_identity] = _admin
    with TestClient(app) as client:
        response = client.post(
            "/v1/ingestion-jobs/documents",
            data={
                "document_json": json.dumps({
                    "canonical_title": "Lease exclusive",
                    "corpus_id": "public",
                    "issuer": "Authority",
                }),
                "version_json": json.dumps({"revision": "1"}),
            },
            files={"file": ("document.txt", b"valid content", "text/plain")},
        )
        assert response.status_code == 202
        queue = client.app.state.ingestion_jobs
        first = queue.claim("worker-a", lease_seconds=30)
        second = queue.claim("worker-b", lease_seconds=30)
        assert first is not None
        assert second is None


def test_object_inventory_reconciliation_detects_missing_and_orphaned_files(tmp_path, admin_identity):
    import hashlib
    from korpus.application.ingestion import ExtractionSettings, IngestionService
    from korpus.application.policy import PolicyEngine
    from korpus.domain.models import AuthorityClass, DocumentCreate, VersionCreate
    from korpus.infrastructure.object_store import LocalObjectStore
    from korpus.infrastructure.repository import SqlRepository

    policy = PolicyEngine()
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'inventory.db'}", "inventory-audit", policy, tmp_path / "anchor.json"
    )
    repository.initialize()
    store = LocalObjectStore(tmp_path / "objects")
    service = IngestionService(repository, store, policy, ExtractionSettings(False, "ukr+eng"))
    content = b"Inventory reconciliation evidence."
    result = service.ingest(
        admin_identity,
        DocumentCreate(canonical_title="Inventory", issuer="Test Issuer"),
        VersionCreate(revision="1", authority=AuthorityClass.OFFICIAL_UA),
        "inventory.txt",
        "text/plain",
        content,
    )
    expected = repository.object_inventory()["content"]
    assert expected == {result.version.object_key}
    assert store.list_keys() == expected
    object_path = store.root / result.version.object_key
    object_path.unlink()
    assert expected - store.list_keys() == {result.version.object_key}
    orphan_hash = hashlib.sha256(b"orphan").hexdigest()
    store.put(b"orphan", orphan_hash, "orphan.txt")
    assert store.list_keys() - expected == {f"{orphan_hash[:2]}/{orphan_hash[2:4]}/{orphan_hash}"}
    repository.close()
