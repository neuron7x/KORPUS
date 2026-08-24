"""An export that cannot show a gap is a clean audit trail over a hole.

A downstream collector has no way to notice a missing audit event by itself: absence
looks like a quiet period. So the export refuses to ship a batch whose sequences jump
or whose hash links do not join, and says in its own manifest what receiving it does
and does not prove.

Payload exclusion is tested as a property rather than a default, because a SIEM is
routinely a lower-classification system than the corpus, and audit payloads quote
corpus material.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from korpus.application.audit_export import (
    CHAIN_LINKED,
    ExportContinuityError,
    batch_manifest,
    build_records,
    to_jsonl,
    verify_continuity,
)


def _rows(count: int, *, start: int = 1, payload: dict[str, Any] | None = None) -> list[dict]:
    rows = []
    previous = "0" * 64
    for index in range(count):
        sequence = start + index
        event_hash = hashlib.sha256(f"event-{sequence}".encode()).hexdigest()
        rows.append(
            {
                "sequence": sequence,
                "event_id": f"00000000-0000-0000-0000-{sequence:012d}",
                "occurred_at": f"2026-08-05T10:00:{sequence:02d}+00:00",
                "actor_subject": "curator",
                "action": "document.ingested",
                "resource_type": "document_version",
                "resource_id": f"doc-{sequence}",
                "payload_json": json.dumps(payload or {"corpus": "public", "spans": sequence}),
                "previous_hash": previous,
                "event_hash": event_hash,
            }
        )
        previous = event_hash
    return rows


def test_a_continuous_batch_is_accepted() -> None:
    """The dual: the refusals below are vacuous if nothing can be exported."""
    records = build_records(_rows(5))

    verify_continuity(records, expected_first_sequence=1)

    assert [record.sequence for record in records] == [1, 2, 3, 4, 5]


def test_payloads_are_excluded_unless_asked_for() -> None:
    """The corpus material an audit payload quotes must not leave by default."""
    records = build_records(_rows(1, payload={"quote": "classified passage"}))

    rendered = records[0].as_dict()

    assert "payload" not in rendered
    assert (
        rendered["payload_sha256"]
        == hashlib.sha256(
            json.dumps(
                {"quote": "classified passage"},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )


def test_payloads_travel_only_when_explicitly_included() -> None:
    records = build_records(_rows(1, payload={"quote": "passage"}), include_payload=True)

    assert records[0].as_dict()["payload"] == {"quote": "passage"}


def test_the_payload_digest_does_not_depend_on_stored_key_order() -> None:
    """Otherwise re-serialising a row would look like the payload had changed."""
    ordered = build_records([{**_rows(1)[0], "payload_json": '{"a":1,"b":2}'}])
    reordered = build_records([{**_rows(1)[0], "payload_json": '{"b": 2, "a": 1}'}])

    assert ordered[0].payload_sha256 == reordered[0].payload_sha256


def test_a_batch_that_skips_the_cursor_is_refused() -> None:
    """Events between the cursor and the batch would never be exported by anyone."""
    records = build_records(_rows(3, start=10))

    with pytest.raises(ExportContinuityError, match="expected 5"):
        verify_continuity(records, expected_first_sequence=5)


def test_a_sequence_gap_inside_the_batch_is_refused() -> None:
    rows = _rows(4)
    del rows[2]

    with pytest.raises(ExportContinuityError, match="sequence gap between 2 and 4"):
        verify_continuity(build_records(rows), expected_first_sequence=1)


def test_a_broken_link_is_refused_even_when_the_sequences_are_consecutive() -> None:
    """Renumbering a forged event is not enough: the chain has to join as well."""
    rows = _rows(3)
    rows[2]["previous_hash"] = hashlib.sha256(b"somewhere else").hexdigest()

    with pytest.raises(ExportContinuityError, match="does not link"):
        verify_continuity(build_records(rows), expected_first_sequence=1)


def test_an_empty_batch_is_not_an_error() -> None:
    """Nothing new since the cursor is the ordinary case, not a failure."""
    verify_continuity([], expected_first_sequence=99)


def test_jsonl_is_one_event_per_line() -> None:
    lines = to_jsonl(build_records(_rows(3))).splitlines()

    assert len(lines) == 3
    assert json.loads(lines[0])["sequence"] == 1


def test_the_manifest_carries_the_cursor_the_collector_asks_with_next() -> None:
    records = build_records(_rows(4, start=7))

    manifest = batch_manifest(records, include_payload=False)

    assert manifest["first_sequence"] == 7
    assert manifest["last_sequence"] == 10
    assert manifest["next_cursor"] == 11
    assert manifest["events"] == 4


def test_the_manifest_states_what_the_hmac_link_does_not_prove() -> None:
    """The comfortable claim is "tamper-evident". It is not true against the key holder."""
    manifest = batch_manifest(build_records(_rows(1)), include_payload=False)

    assert manifest["status"] == CHAIN_LINKED
    interpretation = str(manifest["interpretation"])
    assert "HMAC under a key this system holds" in interpretation
    assert "external anchor" in interpretation


def test_the_batch_digest_changes_when_any_event_changes() -> None:
    """The manifest has to bind the batch it describes, or it describes any batch."""
    first = batch_manifest(build_records(_rows(3)), include_payload=False)
    altered = _rows(3)
    altered[1]["actor_subject"] = "someone-else"
    second = batch_manifest(build_records(altered), include_payload=False)

    assert first["batch_sha256"] != second["batch_sha256"]


def test_an_empty_batch_has_no_cursor_to_advance_to() -> None:
    manifest = batch_manifest([], include_payload=False)

    assert manifest["next_cursor"] is None
    assert manifest["events"] == 0
