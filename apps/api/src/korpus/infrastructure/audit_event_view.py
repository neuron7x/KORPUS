"""Stable JSON projection for one audit-chain row."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from korpus.application.keyring import LEGACY_KEY_ID


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def audit_event_view(row: Any) -> dict[str, object]:
    occurred = row["occurred_at"]
    return {
        "sequence": int(row["sequence"]),
        "event_id": str(row["event_id"]),
        "occurred_at": _iso(occurred) if isinstance(occurred, datetime) else str(occurred),
        "actor_subject": str(row["actor_subject"]),
        "action": str(row["action"]),
        "resource_type": str(row["resource_type"]),
        "resource_id": None if row["resource_id"] is None else str(row["resource_id"]),
        "payload": json.loads(row["payload_json"]),
        "previous_hash": str(row["previous_hash"]),
        "event_hash": str(row["event_hash"]),
        "audit_key_id": str(row["audit_key_id"] or LEGACY_KEY_ID),
    }
