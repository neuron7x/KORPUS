#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from korpus.application.pec_contextual_benchmark import evaluate_contextual_benchmark
from pec_common import read_jsonl, receipt, sha256_file, write_json

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--minimum-informative-pairs", type=int, required=True)
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "reports/PEC_CONTEXTUAL_BENCHMARK_CURRENT.json"
    )
    args = parser.parse_args()
    result = evaluate_contextual_benchmark(
        read_jsonl(args.observations), minimum_informative_pairs=args.minimum_informative_pairs
    )
    report = receipt(
        "pec_contextual_benchmark",
        {
            **result,
            "observations_sha256": sha256_file(args.observations),
        },
    )
    write_json(args.out, report)
    print(json.dumps(report, indent=2))
    return (
        0
        if report["status"] == "PASS" or (report["status"] == "UNKNOWN" and not args.release_gate)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
