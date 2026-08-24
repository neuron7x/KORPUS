#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.production_hard_predicates import (  # noqa: E402
    evaluate_hard_predicates,
    load_hard_predicate_profile,
)
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

PROFILE = ROOT / "config/assurance/production-hard-predicates-v1.json"
GATE_FILES = {
    "redteam": "redteam-gate.json",
    "supply_chain": "supply_chain-gate.json",
    "postgres_security": "postgres_security-gate.json",
    "tevv": "tevv-gate.json",
    "reliability": "reliability-gate.json",
    "exact_environment": "exact_environment-gate.json",
    "final_release": "final_release-gate.json",
    "pec_authority": "pec_authority-gate.json", "pec_canary": "pec_canary-gate.json",
}

def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def build() -> dict[str, Any]:
    profile = load_hard_predicate_profile(PROFILE)
    gate_dir = ROOT / "var/production"
    gates = {gate: _json(gate_dir / filename) for gate, filename in GATE_FILES.items()}
    states = evaluate_hard_predicates(ROOT, profile, gates)
    software_ready = sum(state.software_ready for state in states)
    externally_satisfied = sum(state.externally_satisfied for state in states)
    production_satisfied = sum(state.production_satisfied for state in states)
    return {
        "schema": "korpus.production-hard-predicate-report.v1",
        "release": release_tag(),
        "source_tree_sha256": compute_source_digest(ROOT),
        "profile": str(PROFILE.relative_to(ROOT)),
        "predicates_total": len(states),
        "software_ready": software_ready,
        "externally_satisfied": externally_satisfied,
        "production_satisfied": production_satisfied,
        "software_readiness_percent": round(software_ready / len(states) * 100.0, 6),
        "external_completion_percent": round(externally_satisfied / len(states) * 100.0, 6),
        "production_completion_percent": round(production_satisfied / len(states) * 100.0, 6),
        "states": [state.as_dict() for state in states],
        "interpretation": (
            "Software readiness and external production proof are deliberately separate. "
            "A predicate is production-satisfied only when both are true."
        ),
    }


def main() -> int:
    payload = build()
    out = ROOT / "reports/PRODUCTION_HARD_PREDICATES.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["software_ready"] == payload["predicates_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
