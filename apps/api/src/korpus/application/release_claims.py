from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from korpus.application.provenance import DIGEST_SCOPE
from korpus.application.release_claim_binding import binding, binding_scope
from korpus.application.release_claim_common import EvidenceContext, sha256
from korpus.application.release_claim_contracts import canonical_evidence, contract_valid

CLAIMS = (
    ("CLM-SOURCE-INTEGRITY", "Current source manifest is the release source boundary."),
    ("CLM-REGRESSION", "Current backend regression is source-bound and failure-free."),
    ("CLM-WEB", "Current web lint/build/test surface is source-bound and failure-free."),
    ("CLM-MUTATION", "Declared full mutation catalogue has no surviving valid mutants."),
    (
        "CLM-INFERENCE-SECURITY",
        "Current inference-security suite passes its declared attack surface.",
    ),
    ("CLM-PRODUCTION-AUTH", "System is production-authorized."),
    ("CLM-INDEPENDENT", "System is independently validated."),
)


def _identity(values: tuple[str, ...]) -> tuple[str, str] | None:
    valid = len(values) == 2 and all(isinstance(value, str) for value in values)
    return (values[0], values[1]) if valid else None


def _read_payload(context: EvidenceContext) -> tuple[dict[str, Any] | None, str | None]:
    if context.evidence != canonical_evidence(context.claim_id, context.release):
        return None, "INVALID_EVIDENCE"
    if not sha256(context.source_digest):
        return None, "INVALID_EVIDENCE"
    if not context.path.is_file():
        return None, "PENDING_EVIDENCE"
    if context.path.suffix != ".json":
        return None, "UNDECLARED_EVIDENCE"
    try:
        payload = json.loads(context.path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "INVALID_EVIDENCE"
    if not isinstance(payload, dict):
        return None, "INVALID_EVIDENCE"
    return payload, None


def _binding_status(payload: dict[str, Any], context: EvidenceContext) -> str | None:
    if payload.get("release") != context.release:
        return "STALE_EVIDENCE"
    bound, divergent = binding(payload)
    if divergent:
        return "DIVERGENT_BINDING"
    if bound is None:
        return "UNBOUND_EVIDENCE"
    if bound != context.source_digest:
        return "STALE_EVIDENCE"
    scope, scope_divergent = binding_scope(payload)
    if scope_divergent:
        return "DIVERGENT_SCOPE"
    if scope != DIGEST_SCOPE:
        return "UNSCOPED_EVIDENCE"
    return None


def _claim_status(context: EvidenceContext) -> str:
    payload, refusal = _read_payload(context)
    if payload is None:
        return refusal or "INVALID_EVIDENCE"
    refusal = _binding_status(payload, context)
    if refusal is not None:
        return refusal
    semantic = payload.get("status", payload.get("verdict"))
    if semantic is None:
        return "UNDECLARED_EVIDENCE"
    if not contract_valid(payload, context):
        return "INVALID_EVIDENCE"
    return (
        "SUPPORTED"
        if semantic in ("PASS", "PASS_WITH_EXTERNAL_BLOCKERS")
        else "REFUTED_BY_EVIDENCE"
    )


def claim_status(root: Path, claim_id: str, evidence: str, *identity: str) -> str:
    """Judge one canonical claim; `identity` is exactly `(source_digest, release)`."""
    values = _identity(identity)
    if values is None:
        return "INVALID_EVIDENCE"
    source_digest, release = values
    return _claim_status(EvidenceContext(root, claim_id, evidence, source_digest, release))


def claim_ledger(root: Path, source_digest: str, release: str) -> dict[str, Any]:
    rendered = []
    for claim_id, claim in CLAIMS:
        evidence = canonical_evidence(claim_id, release)
        assert evidence is not None
        rendered.append(
            {
                "id": claim_id,
                "claim": claim,
                "status": claim_status(root, claim_id, evidence, source_digest, release),
                "evidence": evidence,
            }
        )
    return {
        "schema": "korpus.claim-ledger.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "release": release,
        "source_tree_sha256": source_digest,
        "digest_scope": DIGEST_SCOPE,
        "claims": rendered,
    }


__all__ = ["binding", "binding_scope", "claim_ledger", "claim_status"]
