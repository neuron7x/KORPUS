from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _claim_status(root: Path, evidence: str, source_digest: str, release: str) -> str:
    path = root / evidence
    if not path.is_file():
        return "PENDING_EVIDENCE"
    if path.suffix != ".json":
        return "SUPPORTED"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "INVALID_EVIDENCE"
    if not isinstance(payload, dict):
        return "INVALID_EVIDENCE"
    if "release" in payload and payload.get("release") != release:
        return "STALE_EVIDENCE"
    bound = payload.get("source_tree_sha256", payload.get("source_digest"))
    if bound is not None and bound != source_digest:
        return "STALE_EVIDENCE"
    semantic = payload.get("status", payload.get("verdict"))
    return "SUPPORTED" if semantic in (None, "PASS", "PASS_WITH_EXTERNAL_BLOCKERS") else "REFUTED_BY_EVIDENCE"


def claim_ledger(root: Path, source_digest: str, release: str) -> dict[str, Any]:
    claims = [
        ("CLM-SOURCE-INTEGRITY", "Current source manifest is the release source boundary.", "SOURCE_MANIFEST.json"),
        ("CLM-REGRESSION", "Current backend regression is source-bound and failure-free.", f"reports/release/{release}/FULL_BACKEND_REPORT.json"),
        ("CLM-WEB", "Current web lint/build/test surface is source-bound and failure-free.", f"reports/release/{release}/WEB_REGRESSION_REPORT.json"),
        ("CLM-MUTATION", "Declared full mutation catalogue has no surviving valid mutants.", "reports/MUTATION_FULL_CATALOGUE_CURRENT.json"),
        ("CLM-INFERENCE-SECURITY", "Current inference-security suite passes its declared attack surface.", f"reports/release/{release}/INFERENCE_SECURITY_GATE.json"),
    ]
    rendered = [
        {"id": i, "claim": c, "status": _claim_status(root, e, source_digest, release), "evidence": e}
        for i, c, e in claims
    ]
    rendered.extend([
        {"id": "CLM-PRODUCTION-AUTH", "claim": "System is production-authorized.", "status": "REFUTED", "evidence": f"reports/release/{release}/final/BLOCKER_REGISTRY.json"},
        {"id": "CLM-INDEPENDENT", "claim": "System is independently validated.", "status": "REFUTED", "evidence": f"reports/release/{release}/final/BLOCKER_REGISTRY.json"},
    ])
    return {"schema": "korpus.claim-ledger.v2", "generated_at": datetime.now(UTC).isoformat(), "release": release, "source_tree_sha256": source_digest, "claims": rendered}
