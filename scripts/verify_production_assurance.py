#!/usr/bin/env python3
"""Fail closed unless the production assurance report authorizes this exact tree/release."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src")); sys.path.insert(0, str(ROOT / "scripts"))
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=ROOT / "reports/PRODUCTION_ASSURANCE_REPORT.json")
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8")) if args.report.is_file() else {}
    checks = {
        "report_present": bool(report),
        "status_pass": report.get("status") == "PASS",
        "production_authorized": report.get("production_authorized") is True,
        "release_bound": report.get("release") == release_tag(),
        "source_bound": report.get("source_tree_sha256") == compute_source_digest(ROOT),
    }
    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"valid": not failures, "checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
