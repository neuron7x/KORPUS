from __future__ import annotations

from collections.abc import Mapping


def success_payload(
    *, detail_permitted: bool, snapshot: Mapping[str, object], telemetry: str
) -> dict[str, object]:
    if not detail_permitted:
        return {"status": "ready"}
    return {
        "status": "ready",
        "audit_head": int(snapshot["audit_head_sequence"]),
        "telemetry": telemetry,
    }
