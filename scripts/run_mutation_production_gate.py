#!/usr/bin/env python3
"""Promote only complete, current, survivor-free mutation evidence into production."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from candidate_visibility_gate import candidate_visibility_evidence  # noqa: E402
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from mutation_gate_evidence import load_mutation_gate_evidence  # noqa: E402
from release_identity import release_tag  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=ROOT / "var/mutation-report.json")
    parser.add_argument(
        "--snapshot-report", type=Path, default=ROOT / "var/snapshot-mutation-report.json"
    )
    parser.add_argument(
        "--candidate-report",
        type=Path,
        default=ROOT / "var/candidate-visibility-mutation-report.json",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "var/production/mutation-gate.json")
    args = parser.parse_args()

    source = compute_source_digest(ROOT)
    evidence = load_mutation_gate_evidence(args.report, args.snapshot_report, source)
    candidate_checks, candidate = candidate_visibility_evidence(args.candidate_report, source)
    checks = dict(evidence.checks)
    checks.update(candidate_checks)
    failures = [name for name, passed in checks.items() if not passed]

    payload = gate_payload(
        "mutation",
        status="PASS" if not failures else "FAIL",
        source_digest=source,
        release=release_tag(),
        checks=checks,
        failures=failures,
        scope="FULL_CATALOGUE",
        evidence_class="EXECUTED_FIRST_ORDER_MUTATION",
        mutants=evidence.total,
        valid_mutants=evidence.valid,
        killed=evidence.killed,
        snapshot_mutants=evidence.snapshot_total,
        snapshot_killed=evidence.snapshot_killed,
        candidate_visibility=candidate,
        catalogue_components={
            "base": evidence.total,
            "temporal_snapshot": evidence.snapshot_total,
            "candidate_visibility": int(candidate.get("mutants", 0) or 0),
        },
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
