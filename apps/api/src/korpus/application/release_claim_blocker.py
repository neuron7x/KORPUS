from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from korpus.application.production_hard_predicates import (
    evaluate_hard_predicates,
    load_hard_predicate_profile,
)
from korpus.application.release_claim_common import EvidenceContext, load_object

PROFILE = "config/assurance/production-hard-predicates-v1.json"
GATE_FILES = {
    "engineering": "engineering-gate.json",
    "tevv": "tevv-gate.json",
    "observability": "observability-gate.json",
    "state_contracts": "state-contracts-gate.json",
    "authorization": "authorization-gate.json",
    "redteam": "redteam_internal-gate.json",
    "reliability": "reliability-gate.json",
    "inference_security": "inference_security-gate.json",
    "postgres_security": "postgres_security-gate.json",
    "supply_chain": "supply_chain-gate.json",
    "exact_environment": "exact_environment-gate.json",
    "mutation": "mutation-gate.json",
    "pec_authority": "pec_authority-gate.json",
    "pec_canary": "pec_canary-gate.json",
    "final_release": "final_release-gate.json",
}


def _inputs(root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]] | None:
    try:
        profile = load_hard_predicate_profile(root / PROFILE)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    gates = {
        gate: load_object(root / "var/production" / filename) or {}
        for gate, filename in GATE_FILES.items()
    }
    return dict(profile), gates


def _report_valid(context: EvidenceContext) -> bool:
    report = load_object(context.root / "reports/PRODUCTION_HARD_PREDICATES.json")
    inputs = _inputs(context.root)
    if report is None or inputs is None:
        return False
    profile, gates = inputs
    try:
        states = evaluate_hard_predicates(
            context.root,
            profile,
            gates,
            current_source_sha256=context.source_digest,
            current_release=context.release,
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False
    expected = {
        "schema": "korpus.production-hard-predicate-report.v1",
        "release": context.release,
        "source_tree_sha256": context.source_digest,
        "profile": PROFILE,
        "predicates_total": len(states),
        "software_ready": sum(state.software_ready for state in states),
        "externally_satisfied": sum(state.externally_satisfied for state in states),
        "production_satisfied": sum(state.production_satisfied for state in states),
        "states": [state.as_dict() for state in states],
    }
    return all(report.get(key) == value for key, value in expected.items())


def blocker_evidence(payload: dict[str, Any], context: EvidenceContext) -> bool:
    """A blocker registry may refute; PASS needs a distinct authoritative contract."""
    if payload.get("status") == "PASS" or not _report_valid(context):
        return False
    try:
        from korpus.application.release_truth import blocker_registry

        expected = blocker_registry(context.root, context.source_digest, context.release)
    except (ImportError, OSError, ValueError, KeyError, json.JSONDecodeError):
        return False
    if set(payload) != set(expected) or not isinstance(payload.get("generated_at"), str):
        return False
    return all(
        payload.get(field) == value for field, value in expected.items() if field != "generated_at"
    )
