from __future__ import annotations

import json

import pytest
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import delete, select, text

from apps.api.tests.helpers import approve, ingest_text
from korpus.infrastructure.repository import audits


def test_audit_chain_and_external_anchor_verify(client):
    result = ingest_text(client)
    approve(client, result["version"]["id"])
    client.post("/v1/answers", json={"text": "Що має містити запис?"})
    body = client.get("/v1/audit/verify").json()
    assert body["valid"] is True
    assert body["anchor_valid"] is True
    assert body["head_sequence"] == body["event_count"]
    assert body["event_count"] >= 5


def test_audit_chain_detects_payload_tampering(client):
    ingest_text(client)
    repository = client.app.state.repository
    with repository.engine.begin() as connection:
        connection.execute(text("UPDATE audit_events SET payload_json='{}' WHERE sequence=1"))
    body = client.get("/v1/audit/verify").json()
    assert body["valid"] is False
    assert body["first_invalid_sequence"] == 1


def test_audit_anchor_detects_tail_truncation(client):
    ingest_text(client)
    repository = client.app.state.repository
    with repository.engine.begin() as connection:
        last = connection.execute(select(audits.c.sequence).order_by(audits.c.sequence.desc()).limit(1)).scalar_one()
        connection.execute(delete(audits).where(audits.c.sequence == last))
    body = client.get("/v1/audit/verify").json()
    assert body["valid"] is False
    assert "head" in body["reason"] or "anchor" in body["reason"]


def test_audit_anchor_detects_file_tampering(client):
    ingest_text(client)
    path = client.app.state.repository.anchor_store.path
    payload = json.loads(path.read_text())
    payload["sequence"] += 1
    path.write_text(json.dumps(payload))
    body = client.get("/v1/audit/verify").json()
    assert body["valid"] is False
    assert body["anchor_valid"] is False


def test_concurrent_audit_appends_form_one_total_order(client, admin_identity):
    repository = client.app.state.repository

    def append(index: int) -> str:
        return repository.append_audit(
            admin_identity,
            "concurrency.probe",
            "test",
            str(index),
            {"index": index},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        hashes = list(pool.map(append, range(40)))
    assert len(set(hashes)) == 40
    verification = repository.verify_audit()
    assert verification.valid is True
    assert verification.event_count == 40


def test_audit_chain_rejects_re_signed_broken_predecessor_link(client, admin_identity):
    import hashlib
    import hmac

    from sqlalchemy import update

    repository = client.app.state.repository
    for index in range(3):
        repository.append_audit(
            admin_identity,
            "insider.probe",
            "test",
            str(index),
            {"index": index},
        )
    with repository.engine.begin() as connection:
        row = connection.execute(select(audits).where(audits.c.sequence == 2)).mappings().one()
        forged_previous = "f" * 64
        canonical = repository._audit_canonical(
            sequence=row["sequence"],
            event_id=row["event_id"],
            occurred_at=repository._iso(row["occurred_at"]),
            actor_subject=row["actor_subject"],
            action=row["action"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            payload_json=row["payload_json"],
            previous_hash=forged_previous,
        )
        forged_hash = hmac.new(repository.audit_key, canonical, hashlib.sha256).hexdigest()
        connection.execute(
            update(audits)
            .where(audits.c.sequence == 2)
            .values(previous_hash=forged_previous, event_hash=forged_hash)
        )
    verification = repository.verify_audit()
    assert verification.valid is False
    assert verification.first_invalid_sequence == 2
    assert verification.reason == "audit hash mismatch"


def test_committed_audit_anchor_failure_is_recoverable_without_replaying_event(
    client, admin_identity, monkeypatch
):
    from korpus.infrastructure.audit_anchor import AnchorError

    repository = client.app.state.repository
    original_write = repository.anchor_store.write

    def fail_write(*args, **kwargs):
        raise AnchorError("forced anchor outage")

    monkeypatch.setattr(repository.anchor_store, "write", fail_write)
    event_hash = repository.append_audit(
        admin_identity,
        "recoverable.anchor.probe",
        "test",
        "one",
        {"probe": True},
    )
    assert len(event_hash) == 64
    with repository.engine.connect() as connection:
        event_count = connection.execute(select(audits.c.sequence)).all()
    assert len(event_count) == 1

    monkeypatch.setattr(repository.anchor_store, "write", original_write)
    assert repository.reconcile_audit_anchor() == 1
    assert repository.verify_audit().valid is True
    with repository.engine.connect() as connection:
        final_count = connection.execute(select(audits.c.sequence)).all()
    assert len(final_count) == 1
