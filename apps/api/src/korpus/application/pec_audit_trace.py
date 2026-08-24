from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from korpus.application.numeric_contracts import strict_int

from .pec_revision_binding import RevisionBinding


@dataclass(frozen=True)
class AuditTrace:
    event_ids: tuple[str, ...]
    sha256: str


def extract_audit_trace(rows: Iterable[Mapping[str, object]], binding: RevisionBinding) -> AuditTrace:
    materialized = list(rows)
    for row in materialized:
        sequence = row.get("sequence")
        if not strict_int(sequence) or sequence < 0:
            raise ValueError("audit sequence must be a non-negative integer")
    ordered = sorted(materialized, key=lambda row: row["sequence"])
    event_ids: list[str] = []
    canonical: list[dict[str, object]] = []
    previous_sequence = -1
    for row in ordered:
        sequence = row["sequence"]
        if sequence <= previous_sequence:
            raise ValueError("audit sequence must be strictly increasing")
        previous_sequence = sequence
        event_id = str(row.get("event_id", "")).strip()
        if not event_id or event_id in event_ids:
            raise ValueError("audit event IDs must be non-empty and unique")
        if str(row.get("revision", "")) != binding.revision:
            raise ValueError("audit revision binding mismatch")
        if str(row.get("profile", "")) != binding.profile or str(row.get("phase", "")) != binding.phase:
            raise ValueError("audit profile/phase binding mismatch")
        if str(row.get("environment_class", "")) != binding.environment_class:
            raise ValueError("audit environment binding mismatch")
        event_ids.append(event_id)
        canonical.append({"sequence": sequence, "event_id": event_id, "action": str(row.get("action", ""))})
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return AuditTrace(tuple(event_ids), hashlib.sha256(payload).hexdigest())
