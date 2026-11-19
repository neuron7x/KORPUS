#!/usr/bin/env python3
"""Refuse skipped, vulnerable or incomplete native scanner-toolchain audits."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.source_security_contract import strict_json, validate_audit  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        raw = args.report.read_bytes()
        report = strict_json(raw)
        validate_audit(report, ROOT, "scanners")
    except (ValueError, OSError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}))
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "dependencies": len(report["dependencies"]),
                "report_sha256": hashlib.sha256(raw).hexdigest(),
                "production_authorized": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
