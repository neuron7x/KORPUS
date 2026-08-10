#!/usr/bin/env python3
"""Bind the fresh engineering assurance report into the production gate schema."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=ROOT / "reports/RESEARCH_ASSURANCE_REPORT.json")
    parser.add_argument("--out", type=Path, default=ROOT / "var/production/engineering-gate.json")
    args = parser.parse_args()
    source = compute_source_digest(ROOT)
    release = release_tag()
    report = json.loads(args.report.read_text(encoding="utf-8")) if args.report.is_file() else {}
    checks = {
        "report_present": bool(report),
        "research_assurance_pass": report.get("status") == "PASS",
        "source_bound": report.get("source_tree_sha256") == source,
    }
    failures = [name for name, passed in checks.items() if not passed]
    payload = gate_payload(
        "engineering", status="PASS" if not failures else "FAIL", source_digest=source,
        release=release, checks=checks, failures=failures,
        evidence_class="FRESH_LOCAL_ENGINEERING", report=str(args.report.relative_to(ROOT)),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
