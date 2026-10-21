from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

PRODUCTION_AUTHORIZATION_BLOCKERS = (
    "github_hosted_artifact_receipt_pending",
    "completed_github_run_receipt_absent",
    "independent_actor_receipts_absent",
)


class _InvalidJsonValue(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]] | str) -> dict[str, Any]:
    if isinstance(pairs, str):
        raise _InvalidJsonValue(f"non-finite constant {pairs}")
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidJsonValue(f"duplicate key {key!r}")
        result[key] = value
    return result


def strict_signed_json_object(data: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_unique_object)
    except (_InvalidJsonValue, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain an object")
    return value


def failed_candidate_verdict(reason: str) -> dict[str, Any]:
    return {
        "schema": "korpus.release-candidate-checks.v1",
        "status": "FAIL",
        "candidate_checks_passed": False,
        "production_authorized": False,
        "checks": {},
        "failures": [reason],
        "authorization_blockers": list(PRODUCTION_AUTHORIZATION_BLOCKERS),
    }
