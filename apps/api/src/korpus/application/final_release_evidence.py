from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

PRODUCTION_AUTHORIZATION_BLOCKERS = (
    "github_hosted_artifact_receipt_pending",
    "completed_github_run_receipt_absent",
    "independent_actor_receipts_absent",
)


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(repr(key))
        result[key] = value
    return result


def strict_signed_json_object(data: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(data, object_pairs_hook=_unique_object)
    except _DuplicateKey as error:
        raise ValueError(f"{label} contains duplicate key {error}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON") from error
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
