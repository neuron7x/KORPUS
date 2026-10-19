#!/usr/bin/env python3
"""Bind one raw coverage.py report to exact source inputs and an Actions run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.coverage_evidence import stamp_report  # noqa: E402
from korpus.application.github_assurance_receipts import (  # noqa: E402
    identity_from_environment,
    new_receipt,
    sha256_bytes,
)
from source_digest import source_tree_digest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dialect", choices=("sqlite", "postgresql"), required=True)
    parser.add_argument("--job", choices=("sqlite-coverage", "postgres"), required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    identity = identity_from_environment()
    source = source_tree_digest("HEAD")
    value = json.loads(args.report.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("coverage report is not an object")
    stamped = stamp_report(value, dialect=args.dialect, source_tree_sha256=source, root=ROOT)
    args.report.write_text(json.dumps(stamped, ensure_ascii=False) + "\n", encoding="utf-8")
    payload = args.report.read_bytes()
    subject = stamped["korpus_coverage"]
    receipt = new_receipt(
        identity,
        kind=f"coverage-{args.dialect}",
        job=args.job,
        source_tree_sha256=source,
        artifacts={args.report.name: payload},
        subjects={
            "coverage": {
                "dialect": args.dialect,
                "report": args.report.name,
                "report_sha256": sha256_bytes(payload),
                "source_inputs_sha256": subject["source_inputs_sha256"],
                "file_structure_sha256": subject["file_structure_sha256"],
            }
        },
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
