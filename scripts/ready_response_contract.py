"""Semantic /ready response admission; HTTP 200 alone proves no readiness."""

from __future__ import annotations

import json


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate readiness response field")
        result[key] = value
    return result


def ready_response(probe: dict[str, object]) -> bool:
    status, body = probe.get("status"), probe.get("body")
    if type(status) is not int or status != 200 or not isinstance(body, str):
        return False
    try:
        payload = json.loads(body, object_pairs_hook=_unique_fields)
    except (ValueError, TypeError):
        return False
    if not isinstance(payload, dict) or payload.get("status") != "ready":
        return False
    keys = set(payload)
    return keys == {"status"} or (
        keys == {"status", "audit_head", "telemetry"}
        and type(payload["audit_head"]) is int
        and payload["audit_head"] >= 0
        and isinstance(payload["telemetry"], str)
        and bool(payload["telemetry"])
    )
