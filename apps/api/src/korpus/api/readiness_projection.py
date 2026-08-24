from __future__ import annotations

from collections.abc import Mapping

from korpus.application.numeric_contracts import require_count


def success_payload(
    *, detail_permitted: bool, snapshot: Mapping[str, object], telemetry: str
) -> dict[str, object]:
    if not detail_permitted:
        return {"status": "ready"}
    return {
        "status": "ready",
        "audit_head": require_count(snapshot.get("audit_head_sequence"), label="audit head"),
        "telemetry": telemetry,
    }
