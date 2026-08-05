"""Audit events, in a form something outside this system can hold and check.

An audit log that lives only inside the system it audits answers to whoever controls
that system. `TECHNICAL_DEBT_V5.md` records "production SIEM export, retention and
correlation integration" as open, and the gap is not a connector: it is that nothing
here could hand a downstream collector a batch of events together with the means to
notice that the batch is incomplete.

Three properties, and the third is the one that is easy to get wrong.

*Resumable.* Export is by sequence cursor. A collector that received up to N asks for
N+1, so a restart neither loses nor duplicates.

*Gap-evident.* Sequences are consecutive by construction, and each event names the
hash of the one before it. An export whose sequences jump, or whose links do not join,
is refused rather than shipped — a SIEM that silently receives events 1–100 and
104–200 will report a clean audit trail over a hole.

*Honest about what the link proves.* The event hash is an HMAC under a key this system
holds and does not export. So a collector can verify that the batch it received is
internally linked and continuous, and cannot verify that the contents were not
rewritten by someone holding the key. Saying "tamper-evident" without that
qualification would be the more comfortable claim and the false one.

Payloads are excluded by default. Audit payloads quote corpus material — the thing the
classification controls exist for — and a SIEM is routinely a lower-classification
system. The digest travels instead, so a payload can be shown to match later without
the payload having left.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

CHAIN_LINKED = "CHAIN_LINKED_NOT_CONTENT_VERIFIED"
GENESIS = "0" * 64


@dataclass(frozen=True)
class ExportRecord:
    sequence: int
    event_id: str
    occurred_at: str
    actor_subject: str
    action: str
    resource_type: str
    resource_id: str | None
    previous_hash: str
    event_hash: str
    payload_sha256: str
    payload: Mapping[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        rendered: dict[str, Any] = {
            "sequence": self.sequence,
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "actor_subject": self.actor_subject,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
            "payload_sha256": self.payload_sha256,
        }
        if self.payload is not None:
            rendered["payload"] = self.payload
        return rendered


class ExportContinuityError(RuntimeError):
    """The batch is not a continuous, linked run of the audit log."""


def _canonical_payload(payload_json: str) -> str:
    """Re-serialise so the digest does not depend on how the row was stored."""
    return json.dumps(
        json.loads(payload_json), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def build_records(
    rows: Iterable[Mapping[str, Any]], *, include_payload: bool = False
) -> list[ExportRecord]:
    """Turn audit rows into export records, digesting the payload either way."""

    records: list[ExportRecord] = []
    for row in rows:
        payload_json = str(row["payload_json"])
        canonical = _canonical_payload(payload_json)
        records.append(
            ExportRecord(
                sequence=int(row["sequence"]),
                event_id=str(row["event_id"]),
                occurred_at=str(row["occurred_at"]),
                actor_subject=str(row["actor_subject"]),
                action=str(row["action"]),
                resource_type=str(row["resource_type"]),
                resource_id=None if row["resource_id"] is None else str(row["resource_id"]),
                previous_hash=str(row["previous_hash"]),
                event_hash=str(row["event_hash"]),
                payload_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                payload=json.loads(canonical) if include_payload else None,
            )
        )
    return records


def verify_continuity(records: Sequence[ExportRecord], *, expected_first_sequence: int) -> None:
    """Raise unless the batch is a consecutive, correctly linked run.

    Refusing is the whole value. A collector cannot detect a missing event on its own:
    absence looks exactly like a quiet period.
    """
    if not records:
        return
    if records[0].sequence != expected_first_sequence:
        raise ExportContinuityError(
            f"batch starts at sequence {records[0].sequence}, expected "
            f"{expected_first_sequence}: events between them would never be exported"
        )
    for previous, current in pairwise(records):
        if current.sequence != previous.sequence + 1:
            raise ExportContinuityError(
                f"sequence gap between {previous.sequence} and {current.sequence}"
            )
        if current.previous_hash != previous.event_hash:
            raise ExportContinuityError(
                f"event {current.sequence} does not link to {previous.sequence}"
            )


def to_jsonl(records: Sequence[ExportRecord]) -> str:
    """One event per line — the shape every collector reads without a parser."""
    return "".join(
        json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )


def batch_manifest(
    records: Sequence[ExportRecord], *, include_payload: bool
) -> dict[str, Any]:
    """What the batch is, and — as importantly — what receiving it does not prove."""
    return {
        "schema_version": 1,
        "status": CHAIN_LINKED,
        "events": len(records),
        "first_sequence": records[0].sequence if records else None,
        "last_sequence": records[-1].sequence if records else None,
        "next_cursor": (records[-1].sequence + 1) if records else None,
        "payloads_included": include_payload,
        "batch_sha256": hashlib.sha256(to_jsonl(records).encode("utf-8")).hexdigest(),
        "interpretation": (
            "Sequences are consecutive and each event links to the one before it, so a "
            "gap or a reordering in this batch is detectable. The event hash is an "
            "HMAC under a key this system holds and does not export: a collector "
            "cannot verify that the contents were not rewritten by someone holding "
            "that key. Independent detection of that requires the external anchor."
        ),
    }
