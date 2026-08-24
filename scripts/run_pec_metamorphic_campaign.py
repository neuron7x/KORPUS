#!/usr/bin/env python3
"""Verify semantics-preserving PEC query transformations against hard invariants."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.pec_metamorphic import evaluate_metamorphic_pairs
from pec_common import read_jsonl, receipt, sha256_file, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--minimum-pairs", type=int, required=True)
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/PEC_METAMORPHIC_CURRENT.json")
    args = parser.parse_args()
    if args.minimum_pairs < 1:
        raise SystemExit("minimum pairs must be positive")
    result = evaluate_metamorphic_pairs(read_jsonl(args.observations), args.minimum_pairs)
    report = receipt(
        "pec_metamorphic", {**result, "observations_sha256": sha256_file(args.observations)}
    )
    write_json(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return (
        0
        if result["status"] == "PASS" or (result["status"] == "UNKNOWN" and not args.release_gate)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
