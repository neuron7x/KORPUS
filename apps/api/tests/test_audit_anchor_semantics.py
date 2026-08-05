"""A delayed anchor is not a broken chain, and an anchor ahead of the head is.

`verify_audit` used to answer one question with two meanings: `valid` was false
whenever the external anchor was not exactly at the head. The anchor is delivered from
a transactional outbox *outside* the business transaction — deliberately, so that
answering never waits on remote storage — so any burst of writes leaves it briefly
behind. Observed on PostgreSQL with 40 concurrent appends: the chain was intact, every
hash verified, and `/v1/audit/verify` reported the audit as broken.

For a system whose operators are told to stop on an audit failure, a verdict that
cannot distinguish "delivery is a second behind" from "somebody rewrote the log" is
worse than no verdict.

The distinction stated here:
  - anchor behind the head, agreeing with the event at its own position → intact,
    `anchor_pending` counts the undelivered checkpoints;
  - anchor disagreeing with the event at its position → the chain was rewritten;
  - anchor ahead of the head → the database lost committed rows.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from korpus.domain.models import Identity

from apps.api.tests.helpers import ingest_text


def test_a_burst_of_appends_leaves_the_chain_valid(
    client: TestClient, admin_identity: Identity
) -> None:
    """The reproduction: concurrent writers, intact chain, verdict must stay true."""
    repository = client.app.state.repository

    def append(index: int) -> str:
        return repository.append_audit(
            admin_identity, "burst.probe", "test", str(index), {"index": index}
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        hashes = list(pool.map(append, range(40)))

    verification = repository.verify_audit()

    assert len(set(hashes)) == 40
    assert verification.valid is True, verification.reason
    assert verification.event_count == 40


def test_an_anchor_behind_the_head_is_pending_not_invalid(
    client: TestClient, admin_identity: Identity
) -> None:
    repository = client.app.state.repository
    first = repository.append_audit(admin_identity, "anchor.probe", "test", "1", {"n": 1})
    repository.append_audit(admin_identity, "anchor.probe", "test", "2", {"n": 2})
    # The store is monotonic by design, so an anchor cannot be moved backwards;
    # resetting and re-writing reproduces the state a slow delivery leaves.
    repository.anchor_store.reset()
    repository.anchor_store.write(1, first)

    verification = repository.verify_audit()

    assert verification.valid is True, verification.reason
    assert verification.anchor_valid is False
    assert verification.anchor_pending == 1


def test_an_anchor_that_disagrees_at_its_own_position_is_invalid(
    client: TestClient, admin_identity: Identity
) -> None:
    """The property the anchor exists for: the chain was rewritten under it."""
    repository = client.app.state.repository
    repository.append_audit(admin_identity, "anchor.probe", "test", "1", {"n": 1})
    repository.append_audit(admin_identity, "anchor.probe", "test", "2", {"n": 2})
    repository.anchor_store.reset()
    repository.anchor_store.write(1, "f" * 64)

    verification = repository.verify_audit()

    assert verification.valid is False
    assert verification.anchor_valid is False
    assert verification.reason == "external audit anchor mismatch"


def test_an_anchor_ahead_of_the_head_is_invalid(
    client: TestClient, admin_identity: Identity
) -> None:
    """A restore from an older backup, or committed rows that are gone."""
    repository = client.app.state.repository
    head = repository.append_audit(admin_identity, "anchor.probe", "test", "1", {"n": 1})
    repository.anchor_store.write(9, head)

    verification = repository.verify_audit()

    assert verification.valid is False
    assert verification.reason == "external audit anchor is ahead of the database head"


def test_the_verification_endpoint_reports_pending_delivery(client: TestClient) -> None:
    """Operators read this over HTTP, so the field has to reach them."""
    ingest_text(client)

    payload = client.get("/v1/audit/verify").json()

    assert "anchor_pending" in payload, json.dumps(payload, ensure_ascii=False)
