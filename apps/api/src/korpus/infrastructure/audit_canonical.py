"""Canonical byte encoding shared by audit writer and verifier."""

from __future__ import annotations

import json


def audit_canonical(
    *,
    sequence: int,
    event_id: str,
    occurred_at: str,
    actor_subject: str,
    action: str,
    resource_type: str,
    resource_id: str | None,
    payload_json: str,
    previous_hash: str,
) -> bytes:
    return json.dumps(
        {
            "schema": 1,
            "sequence": sequence,
            "event_id": event_id,
            "occurred_at": occurred_at,
            "actor_subject": actor_subject,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "payload_json": payload_json,
            "previous_hash": previous_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
