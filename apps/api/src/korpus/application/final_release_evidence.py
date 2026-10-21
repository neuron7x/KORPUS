from __future__ import annotations

from typing import Any

from korpus.application.strict_json import strict_json_object as strict_signed_json_object

__all__ = [
    "PRODUCTION_AUTHORIZATION_BLOCKERS",
    "failed_candidate_verdict",
    "strict_signed_json_object",
]

PRODUCTION_AUTHORIZATION_BLOCKERS = (
    "github_hosted_artifact_receipt_pending",
    "completed_github_run_receipt_absent",
    "independent_actor_receipts_absent",
)


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
