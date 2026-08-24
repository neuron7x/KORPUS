"""Isolation between subjects, an integrity probe that can fail, and an audit you can read.

- `AdmissionController` bounded the service globally. One subject issuing `capacity`
  concurrent queries took all of it and everyone else got 503. Rate limiting existed
  only as nginx `limit_req` on `$binary_remote_addr`: bypassed by reaching `api:8000`,
  shared by everyone behind one NAT, blind to who authenticated, and untested.
- `healthcheck()` was `SELECT 1`. A corrupt but readable database reports healthy.
- Audit could be verified whole and read not at all, so "why was this answer withheld"
  meant exporting the table.

`per-subject-isolation`, `refill-capped-at-capacity`, `integrity-check-fail-closed` and
`audit-read-scoped-to-trace` in docs/audit/INVARIANT_DIFF_2026-08-03.md.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from korpus.application.resilience import AdmissionController, OverloadedError
from korpus.domain.models import Identity
from korpus.infrastructure.repository import SqlRepository
from korpus.release import RELEASE_VERSION

from apps.api.tests.conftest import set_identity
from apps.api.tests.helpers import approve, ingest_text

MARKER = "СЛІД"


def test_one_subject_cannot_take_the_whole_service() -> None:
    controller = AdmissionController(capacity=4, per_subject_limit=2)

    with controller.acquire("loud"), controller.acquire("loud"):
        with pytest.raises(OverloadedError, match="per-subject") as refused:
            with controller.acquire("loud"):
                pass
        assert refused.value.reason.value == "subject_share_exhausted"
        with controller.acquire("quiet"):
            assert controller.snapshot().active == 3, (
                "another subject must still be admitted while one is at its share"
            )


def test_the_per_subject_share_is_returned_when_the_work_finishes() -> None:
    """A leaked slot is a slow denial of service; the count must come back down."""
    controller = AdmissionController(capacity=4, per_subject_limit=1)

    for _ in range(5):
        with controller.acquire("repeat"):
            pass

    with controller.acquire("repeat"):
        assert controller.snapshot().active == 1


def test_a_rejected_subject_does_not_leak_its_slot() -> None:
    controller = AdmissionController(capacity=4, per_subject_limit=1)

    with controller.acquire("loud"), pytest.raises(OverloadedError), controller.acquire("loud"):
        pass

    with controller.acquire("loud"):
        assert controller.snapshot().active == 1, (
            "the refused attempt must not have consumed the subject's share"
        )


def test_the_subject_table_does_not_grow_without_bound() -> None:
    """An unbounded map keyed on caller-chosen strings is its own denial of service."""
    controller = AdmissionController(capacity=4, per_subject_limit=1)

    for index in range(500):
        with controller.acquire(f"subject-{index}"):
            pass

    assert controller._by_subject == {}


def test_a_default_share_leaves_room_for_someone_else() -> None:
    assert AdmissionController(capacity=8).per_subject_limit == 4
    assert AdmissionController(capacity=1).per_subject_limit == 1, (
        "a capacity of one must still admit somebody"
    )


def test_healthcheck_fails_on_a_corrupt_database(tmp_path: Path) -> None:
    """Readable is not intact: the probe has to be able to fail."""
    database = tmp_path / "corrupt.db"
    repository = SqlRepository(
        f"sqlite:///{database}", audit_hmac_key="k" * 32, audit_anchor_path=tmp_path / "anchor.json"
    )
    repository.initialize()
    assert repository.healthcheck() is True
    repository.close()

    with sqlite3.connect(database) as raw:
        page_size = raw.execute("PRAGMA page_size").fetchone()[0]
    with database.open("r+b") as handle:
        handle.seek(page_size * 2)
        handle.write(b"\x00" * page_size)

    broken = SqlRepository(
        f"sqlite:///{database}", audit_hmac_key="k" * 32, audit_anchor_path=tmp_path / "anchor.json"
    )
    try:
        assert broken.healthcheck() is False, (
            "SELECT 1 succeeds against a corrupt file; the integrity probe must not"
        )
    finally:
        broken.close()


def test_an_auditor_reads_the_events_of_one_request(client: TestClient) -> None:
    result = ingest_text(client, text=f"Маркер {MARKER} у затвердженому наказі підрозділу.")
    approve(client, result["version"]["id"])

    answered = client.post(
        "/v1/answers",
        json={"text": f"де згадано {MARKER}"},
        headers={
            "X-Request-ID": "trace-under-test",
            "X-KORPUS-Client-Version": "v0.6.0-test",
            "Authorization": "Bearer test-credential",
        },
    )
    assert answered.status_code == 200

    events = client.get("/v1/audit/events", params={"trace_id": "trace-under-test"}).json()

    assert events, "the answer wrote at least one event under this trace"
    assert all(event["payload"]["trace_id"] == "trace-under-test" for event in events)
    assert [event["sequence"] for event in events] == sorted(
        event["sequence"] for event in events
    )
    completed = next(event for event in events if event["action"] == "answer.completed")
    payload = completed["payload"]
    assert payload["client_version"] == "v0.6.0-test"
    assert payload["service_version"] == RELEASE_VERSION
    assert payload["offline_mode"] is False
    assert payload["policy_decision_id"].startswith("pd1:")
    assert payload["session_binding"] is not None
    assert completed["event_hash"] and len(completed["event_hash"]) == 64
    assert completed["previous_hash"] and len(completed["previous_hash"]) == 64
    assert completed["audit_key_id"]


def test_the_trace_scope_excludes_other_requests(client: TestClient) -> None:
    result = ingest_text(client, text=f"Маркер {MARKER} у затвердженому наказі підрозділу.")
    approve(client, result["version"]["id"])
    client.post(
        "/v1/answers",
        json={"text": f"де згадано {MARKER}"},
        headers={"X-Request-ID": "trace-alpha"},
    )
    client.post(
        "/v1/answers",
        json={"text": f"де згадано {MARKER}"},
        headers={"X-Request-ID": "trace-beta"},
    )

    alpha = client.get("/v1/audit/events", params={"trace_id": "trace-alpha"}).json()

    assert alpha
    assert all(event["payload"]["trace_id"] == "trace-alpha" for event in alpha), (
        "a scoped read that returns another request's events is not scoped"
    )


def test_reading_the_audit_requires_the_audit_permission(
    client: TestClient, public_identity: Identity
) -> None:
    set_identity(client, public_identity)

    refusal = client.get("/v1/audit/events", params={"trace_id": "trace-alpha"})

    assert refusal.status_code == 403


def test_a_malformed_trace_id_is_refused(client: TestClient) -> None:
    refusal = client.get("/v1/audit/events", params={"trace_id": "trace with spaces"})

    assert refusal.status_code == 400
