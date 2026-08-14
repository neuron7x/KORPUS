#!/usr/bin/env python3
"""Promote only complete, current, survivor-free mutation evidence."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))
from candidate_visibility_gate import candidate_visibility_evidence  # noqa: E402
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest, read_provenance  # noqa: E402
from release_identity import release_tag  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=ROOT / "var/mutation-report.json")
    candidate_report = ROOT / "var/candidate-visibility-mutation-report.json"
    parser.add_argument("--candidate-report", type=Path, default=candidate_report)
    parser.add_argument("--out", type=Path, default=ROOT / "var/production/mutation-gate.json")
    args = parser.parse_args()
    source = compute_source_digest(ROOT)
    report = json.loads(args.report.read_text(encoding="utf-8")) if args.report.is_file() else {}
    try:
        provenance = read_provenance(report) if report else None
        provenance_current = provenance is not None and provenance.source_digest == source
    except (TypeError, ValueError):
        provenance_current = False
    total = int(report.get("mutants", 0) or 0)
    valid = int(report.get("valid_mutants", 0) or 0)
    killed = int(report.get("killed", 0) or 0)
    checks = {
        "report_present": bool(report), "source_bound": provenance_current,
        "catalogue_nonempty": total > 0,
        "all_mutants_valid": valid == total and not report.get("invalid"),
        "all_valid_mutants_killed": killed == valid and not report.get("survived"),
        "catalogue_score_one": report.get("mutation_score_over_catalogue") == 1.0,
    }
    candidate_checks, candidate = candidate_visibility_evidence(args.candidate_report, source)
    checks.update(candidate_checks)
    failures = [name for name, passed in checks.items() if not passed]
    payload = gate_payload(
        "mutation", status="PASS" if not failures else "FAIL", source_digest=source,
        release=release_tag(), checks=checks, failures=failures, scope="FULL_CATALOGUE",
        evidence_class="EXECUTED_FIRST_ORDER_MUTATION", mutants=total,
        valid_mutants=valid, killed=killed, candidate_visibility=candidate,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
