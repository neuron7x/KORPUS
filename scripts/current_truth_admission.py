from __future__ import annotations

import json
from pathlib import Path

try:
    from .current_truth_contract import load_object
except ImportError:  # direct script execution with scripts/ on sys.path
    from current_truth_contract import load_object  # type: ignore[no-redef]


def _current_json(path: Path, release: str, digest: str) -> bool:
    try:
        payload = load_object(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if "release" in payload and payload.get("release") != release:
        return False
    bound = payload.get("source_tree_sha256", payload.get("source_digest"))
    return bound is None or bound == digest


def claim_admission_checks(root: Path, release: str, digest: str) -> dict[str, bool]:
    ledger = root / f"reports/release/{release}/final/CLAIM_LEDGER.json"
    if not ledger.is_file():
        return {"CLAIM_LEDGER.supported_evidence_resolves": False}
    unresolved = 0
    for claim in load_object(ledger).get("claims", ()):
        if not isinstance(claim, dict) or not str(claim.get("status", "")).startswith("SUPPORTED"):
            continue
        evidence = claim.get("evidence")
        if not isinstance(evidence, str) or not evidence:
            unresolved += 1
            continue
        target = root / evidence
        if not target.is_file() or (
            target.suffix == ".json" and not _current_json(target, release, digest)
        ):
            unresolved += 1
    return {
        "CLAIM_LEDGER.supported_evidence_resolves": unresolved == 0,
        "CLAIM_LEDGER.supported_unresolved_zero": unresolved == 0,
    }


def blocker_state_checks(root: Path, release: str, digest: str) -> dict[str, bool]:
    path = root / f"reports/release/{release}/final/BLOCKER_REGISTRY.json"
    if not path.is_file():
        return {"BLOCKER_REGISTRY.current_state_present": False}
    payload = load_object(path)
    return {
        "BLOCKER_REGISTRY.current_state_present": True,
        "BLOCKER_REGISTRY.hard_predicate_report_current": payload.get(
            "hard_predicate_report_current"
        )
        is True,
        "BLOCKER_REGISTRY.internal_executable_unresolved_zero": payload.get(
            "internal_executable_unresolved"
        )
        == 0,
        "BLOCKER_REGISTRY.source_bound_current": payload.get("source_tree_sha256") == digest,
        "BLOCKER_REGISTRY.release_bound_current": payload.get("release") == release,
    }
