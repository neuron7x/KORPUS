from __future__ import annotations

from typing import Any

from korpus.application.release_claim_backend_receipts import (
    MERGE_PATH,
    backend_artifacts,
    merge_valid,
)
from korpus.application.release_claim_common import EvidenceContext, load_object
from korpus.application.release_claim_hosted_contract import hosted_execution_admitted


def backend_evidence(payload: dict[str, Any], context: EvidenceContext) -> bool:
    merge = load_object(context.root / MERGE_PATH)
    if merge is None or not merge_valid(merge, context):
        return False
    junit = merge["junit"]
    projection = {
        "schema": "korpus.full-backend-report.v2",
        "status": "PASS",
        "release": context.release,
        "source_tree_sha256": context.source_digest,
        "digest_scope": "evidence_paths",
        "collection_digest": merge["collection_digest"],
        "collected": merge["collection_count"],
        "passed": junit["tests"] - junit["failures"] - junit["errors"] - junit["skipped"],
        "failed": junit["failures"],
        "errors": junit["errors"],
        "skipped": junit["skipped"],
        "shards": merge["shards"],
        "evidence_source": MERGE_PATH,
    }
    result = {
        "tests": junit["tests"],
        "failures": junit["failures"],
        "errors": junit["errors"],
        "skipped": junit["skipped"],
        "collection_digest": merge["collection_digest"],
        "shards": merge["shards"],
    }
    return payload == projection and hosted_execution_admitted(
        context, backend_artifacts(context, merge["shards"]), result
    )
