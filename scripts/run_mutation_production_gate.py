#!/usr/bin/env python3
"""Promote only a complete, current, survivor-free mutation catalogue into production evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest, read_provenance  # noqa: E402
from korpus.application.release_numeric import mutation_checks  # noqa: E402
from korpus.application.numeric_contracts import exact_one as _score_is_exact_one, nonnegative_count as _nonnegative_count  # noqa: E402
from release_identity import release_tag  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=ROOT / "var/mutation-report.json")
    parser.add_argument("--out", type=Path, default=ROOT / "var/production/mutation-gate.json")
    args = parser.parse_args()
    source = compute_source_digest(ROOT)
    release = release_tag()
    report = json.loads(args.report.read_text(encoding="utf-8")) if args.report.is_file() else {}
    try:
        provenance = read_provenance(report) if report else None
        provenance_current = provenance is not None and provenance.source_digest == source
    except (TypeError, ValueError):
        provenance_current = False
    checks, total, valid, killed = mutation_checks(report, provenance_current)
    failures = [name for name, passed in checks.items() if not passed]
    payload = gate_payload(
        "mutation", status="PASS" if not failures else "FAIL", source_digest=source,
        release=release, checks=checks, failures=failures, scope="FULL_CATALOGUE",
        evidence_class="EXECUTED_FIRST_ORDER_MUTATION", mutants=total, valid_mutants=valid, killed=killed,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
