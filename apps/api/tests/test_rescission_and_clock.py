"""Withdrawal is an act the corpus can record, and validity does not depend on the host clock.

`rescinded_at` was read when deciding validity, had a mutant in the catalogue and was
described in the import protocol — and no code path wrote it. The only way to take an
order out of force was REJECTED: a review verdict, without reviewer mandate, without
separation of duties, and irreversible. For a system of normative acts, being unable to
record that the issuing body withdrew a document is not a gap in convenience.

Separately, `as_of` defaulted to `date.today()`, which reads the host's local calendar.
Two replicas in different zones answered the same question at the same instant
differently, and no Dockerfile, compose file or manifest pinned the zone.

§2.0.2 and §2.0.3 of docs/operations/ADMISSION_BOUNDARY_2026-08-03.md.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from korpus.domain.models import Identity, QueryRequest

from apps.api.tests.conftest import set_identity
from apps.api.tests.helpers import approve, ingest_text

MARKER = "СКАСУВАННЯ"
BODY = f"Маркер {MARKER} діє доти, доки наказ не скасовано органом, що його видав."


def _ask(client: TestClient, as_of: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"text": f"що каже {MARKER}"}
    if as_of is not None:
        payload["as_of"] = as_of
    response = client.post("/v1/answers", json=payload)
    assert response.status_code == 200, response.text
    answer: dict[str, object] = response.json()
    return answer


def test_an_approved_order_can_be_withdrawn(client: TestClient) -> None:
    result = ingest_text(client, text=BODY)
    approve(client, result["version"]["id"])
    assert _ask(client)["status"] == "answered"

    response = client.post(
        f"/v1/document-versions/{result['version']['id']}/rescission",
        json={"note": "withdrawn by the issuing authority on exercise order 12"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["rescinded_at"] is not None
    assert response.json()["review_state"] == "approved", (
        "withdrawal is not a review verdict; the review history stays as it was"
    )
    assert _ask(client)["status"] == "insufficient_evidence"


def test_withdrawal_is_dated_and_the_day_before_still_answers(client: TestClient) -> None:
    result = ingest_text(client, text=BODY)
    approve(client, result["version"]["id"])
    stamp = datetime.now(UTC)

    client.post(
        f"/v1/document-versions/{result['version']['id']}/rescission",
        json={
            "note": "withdrawn with an explicit effective moment",
            "rescinded_at": stamp.isoformat(),
        },
    )

    yesterday = (stamp - timedelta(days=1)).date().isoformat()
    assert _ask(client, yesterday)["status"] == "answered", (
        "a question about a date before the withdrawal is still governed by the order"
    )
    assert _ask(client, stamp.date().isoformat())["status"] == "insufficient_evidence"


def test_withdrawal_is_recorded_in_the_audit_chain(client: TestClient) -> None:
    result = ingest_text(client, text=BODY)
    approve(client, result["version"]["id"])

    client.post(
        f"/v1/document-versions/{result['version']['id']}/rescission",
        json={"note": "withdrawn by the issuing authority on exercise order 12"},
        headers={"X-Request-ID": "rescission-trace"},
    )

    events = client.get("/v1/audit/events", params={"trace_id": "rescission-trace"}).json()
    assert any(event["action"] == "document.rescinded" for event in events)
    assert client.app.state.repository.verify_audit().valid


def test_withdrawing_twice_is_refused_as_already_withdrawn(client: TestClient) -> None:
    """And says so: "already rescinded" and "write raced" are different operator states.

    The row guard alone also produces a 409, by way of a zero-row update reported as a
    concurrency failure — which would send an operator looking for a second writer that
    does not exist. The state check names the actual condition, and the first
    withdrawal's date must survive the second attempt.
    """
    result = ingest_text(client, text=BODY)
    approve(client, result["version"]["id"])
    body = {"note": "withdrawn by the issuing authority on exercise order 12"}
    first = client.post(f"/v1/document-versions/{result['version']['id']}/rescission", json=body)
    stamped = first.json()["rescinded_at"]

    second = client.post(f"/v1/document-versions/{result['version']['id']}/rescission", json=body)

    assert second.status_code == 409
    assert "already rescinded" in second.json()["detail"], second.json()["detail"]
    current = client.app.state.repository.get_version(
        client.identity_provider.current, UUID(result["version"]["id"])
    )
    assert current is not None
    assert current.rescinded_at is not None
    # Compared as instants, not as strings: the API serialises UTC as `…Z` and psycopg
    # returns `…+00:00` for the same moment, so a string comparison tests the driver.
    assert current.rescinded_at == datetime.fromisoformat(str(stamped).replace("Z", "+00:00")), (
        "the second attempt must not move the date the first one recorded"
    )


def test_an_unapproved_version_cannot_be_withdrawn(client: TestClient) -> None:
    result = ingest_text(client, text=BODY)

    response = client.post(
        f"/v1/document-versions/{result['version']['id']}/rescission",
        json={"note": "withdrawing something that never entered force"},
    )

    assert response.status_code == 409
    assert "approved" in response.json()["detail"]


def test_withdrawal_requires_the_approval_permission(
    client: TestClient, public_identity: Identity
) -> None:
    result = ingest_text(client, text=BODY)
    approve(client, result["version"]["id"])
    set_identity(client, public_identity)

    response = client.post(
        f"/v1/document-versions/{result['version']['id']}/rescission",
        json={"note": "withdrawal attempted without the mandate"},
    )

    assert response.status_code == 403


def test_the_default_as_of_does_not_depend_on_the_host_timezone() -> None:
    """The same instant, two zones, one answer date."""
    previous = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Etc/GMT+12"
        time.tzset()
        west = QueryRequest(text="питання про дату").as_of
        os.environ["TZ"] = "Etc/GMT-14"
        time.tzset()
        east = QueryRequest(text="питання про дату").as_of
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()

    assert west == east == datetime.now(UTC).date(), (
        "validity is a property of the corpus, not of where the process runs"
    )
