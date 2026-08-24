"""Runtime delivery predicates for the GCP production lane."""
from __future__ import annotations


def evaluate(s: object) -> list[tuple[str, bool, str]]:
    return [(
        "PRODUCTION_WORKFLOW_DIGEST_SCAN",
        s.production_workflow.count('python scripts/gcp/verify_container_vulnerabilities.py') == 3
        and 'gcloud artifacts docker images describe' in s.production_workflow
        and '^sha256:[0-9a-f]{64}$' in s.production_workflow,
        "API, web, and mirrored ClamAV candidates resolve to registry digests and are scanned before runtime",
    )]
