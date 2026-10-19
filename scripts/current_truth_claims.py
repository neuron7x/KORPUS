from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from korpus.application.release_claims import claim_ledger, claim_status

try:
    from .current_truth_contract import load_object
except ImportError:  # direct script execution with scripts/ on sys.path
    from current_truth_contract import load_object


CHECK_KEYS = (
    "CLAIM_LEDGER.exact_canonical_ledger",
    "CLAIM_LEDGER.supported_evidence_resolves",
    "CLAIM_LEDGER.supported_unresolved_zero",
    "CLAIM_LEDGER.has_supported_claims",
    "CLAIM_LEDGER.every_claim_decided_by_evidence",
    "CLAIM_LEDGER.status_matches_evidence",
)


def _failed() -> dict[str, bool]:
    return {key: False for key in CHECK_KEYS}


def _evidence_resolves(root: Path, claim: dict[str, object], release: str, digest: str) -> bool:
    evidence, claim_id, declared = claim.get("evidence"), claim.get("id"), claim.get("status")
    if not all(isinstance(value, str) and value for value in (evidence, claim_id, declared)):
        return False
    actual = claim_status(root, claim_id, evidence, digest, release)
    return actual == declared and actual in {"SUPPORTED", "REFUTED_BY_EVIDENCE"}


def _canonical_payload(root: Path, release: str, digest: str) -> dict[str, object] | None:
    try:
        return cast(dict[str, object], claim_ledger(root, digest, release))
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _exact_payload(payload: dict[str, object], expected: dict[str, object]) -> bool:
    comparable = {key: value for key, value in payload.items() if key != "generated_at"}
    canonical = {key: value for key, value in expected.items() if key != "generated_at"}
    return set(payload) == set(expected) and comparable == canonical


def claim_admission_checks(root: Path, release: str, digest: str) -> dict[str, bool]:
    path = root / f"reports/release/{release}/final/CLAIM_LEDGER.json"
    if not path.is_file():
        return _failed()
    try:
        payload = load_object(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return _failed()
    expected = _canonical_payload(root, release, digest)
    if expected is None:
        return _failed()
    exact = _exact_payload(payload, expected)
    entries = payload.get("claims")
    if not isinstance(entries, list) or not all(isinstance(claim, dict) for claim in entries):
        return _failed()
    supported = [claim for claim in entries if claim.get("status") == "SUPPORTED"]
    resolved = bool(supported) and all(
        _evidence_resolves(root, claim, release, digest) for claim in supported
    )
    all_decided = bool(entries) and all(
        _evidence_resolves(root, claim, release, digest) for claim in entries
    )
    return {
        "CLAIM_LEDGER.exact_canonical_ledger": exact,
        "CLAIM_LEDGER.supported_evidence_resolves": resolved,
        "CLAIM_LEDGER.supported_unresolved_zero": resolved,
        "CLAIM_LEDGER.has_supported_claims": bool(supported),
        "CLAIM_LEDGER.every_claim_decided_by_evidence": all_decided,
        "CLAIM_LEDGER.status_matches_evidence": exact and all_decided,
    }
