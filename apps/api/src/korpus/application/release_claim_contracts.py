from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from korpus.application.release_claim_admission import canonical_paths_admitted
from korpus.application.release_claim_backend import backend_evidence
from korpus.application.release_claim_blocker import blocker_evidence
from korpus.application.release_claim_common import (
    EvidenceContext,
    integer,
    sha256,
)
from korpus.application.release_claim_inference import inference_evidence
from korpus.application.release_claim_mutation import mutation_evidence
from korpus.application.release_claim_web import web_evidence


def canonical_evidence(claim_id: str, release: str) -> str | None:
    paths = {
        "CLM-SOURCE-INTEGRITY": "reports/SOURCE_MANIFEST_VERIFICATION_CURRENT.json",
        "CLM-REGRESSION": f"reports/release/{release}/FULL_BACKEND_REPORT.json",
        "CLM-WEB": f"reports/release/{release}/WEB_REGRESSION_REPORT.json",
        "CLM-MUTATION": "reports/MUTATION_FULL_CATALOGUE_CURRENT.json",
        "CLM-INFERENCE-SECURITY": f"reports/release/{release}/INFERENCE_SECURITY_GATE.json",
        "CLM-PRODUCTION-AUTH": f"reports/release/{release}/final/BLOCKER_REGISTRY.json",
        "CLM-INDEPENDENT": f"reports/release/{release}/final/BLOCKER_REGISTRY.json",
    }
    return paths.get(claim_id)


def _source_manifest(payload: dict[str, Any], context: EvidenceContext) -> bool:
    valid, failures = payload.get("valid"), payload.get("failures")
    if (
        payload.get("schema") != "korpus.source-manifest-verification.v1"
        or valid is not True
        or payload.get("status") != "PASS"
        or not isinstance(failures, list)
        or failures
        or not integer(payload.get("files"), minimum=1)
        or not sha256(payload.get("root_sha256"))
    ):
        return False
    try:
        from scripts.verify_source_manifest import verify

        observed = verify(context.root)
    except (ImportError, OSError, ValueError, KeyError, json.JSONDecodeError):
        return False
    return all(
        payload.get(field) == observed.get(field)
        for field in ("valid", "files", "root_sha256", "failures")
    )


def contract_valid(payload: dict[str, Any], context: EvidenceContext) -> bool:
    if context.evidence != canonical_evidence(context.claim_id, context.release):
        return False
    if payload.get("release") != context.release:
        return False
    if not canonical_paths_admitted(context.root, [context.evidence]):
        return False
    validators: dict[str, Callable[[dict[str, Any], EvidenceContext], bool]] = {
        "CLM-SOURCE-INTEGRITY": _source_manifest,
        "CLM-REGRESSION": backend_evidence,
        "CLM-WEB": web_evidence,
        "CLM-MUTATION": mutation_evidence,
        "CLM-INFERENCE-SECURITY": inference_evidence,
        "CLM-PRODUCTION-AUTH": blocker_evidence,
        "CLM-INDEPENDENT": blocker_evidence,
    }
    validator = validators.get(context.claim_id)
    return validator(payload, context) if validator is not None else False
