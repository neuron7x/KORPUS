#!/usr/bin/env python3
"""Compare PEC ablations on exactly the same locked tasks and evidence bindings."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.pec_ablation import compare_ablation
from pec_common import receipt, sha256_file, write_json

ROW_KEYS = ("cases", "rows", "observations", "details")
BINDING_KEYS = (
    "dataset_sha256",
    "source_digest",
    "corpus_release_id",
    "evaluation_protocol_sha256",
    "answer_calibration_id",
    "provider_model_id",
    "provider_config_sha256",
    "time_budget_ms",
)


def _named(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected NAME=PATH")
    name, path = value.split("=", 1)
    if not name or not path:
        raise argparse.ArgumentTypeError("expected non-empty NAME=PATH")
    return name, Path(path)


def _rows(raw: dict[str, object]) -> dict[str, dict[str, object]]:
    values = next((raw.get(key) for key in ROW_KEYS if isinstance(raw.get(key), list)), None)
    if values is None:
        raise ValueError("ablation result has no cases/rows/observations/details array")
    output: dict[str, dict[str, object]] = {}
    for row in values:
        if not isinstance(row, dict):
            raise ValueError("ablation row must be an object")
        query_id = str(row.get("query_id") or row.get("id") or "")
        if not query_id or query_id in output:
            raise ValueError(f"duplicate_or_empty_query_id:{query_id}")
        output[query_id] = row
    return output


def _binding(raw: dict[str, object]) -> tuple[str, ...]:
    return tuple(str(raw.get(key, "")) for key in BINDING_KEYS)



def _compare_candidates(
    candidates: list[tuple[str, Path]],
    baseline_rows: dict[str, dict[str, object]],
    baseline_binding: tuple[str, ...],
    minimum_pairs: int,
) -> tuple[dict[str, object], list[str]]:
    comparisons: dict[str, object] = {}
    failures: list[str] = []
    for name, path in candidates:
        raw = json.loads(path.read_text())
        if _binding(raw) != baseline_binding:
            failures.append(name)
            comparisons[name] = {"status": "FAIL", "reason": "binding_mismatch"}
            continue
        comparisons[name] = compare_ablation(
            baseline_rows, _rows(raw), minimum_pairs=minimum_pairs
        )
    return comparisons, failures

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=_named, required=True)
    parser.add_argument("--candidate", type=_named, action="append", required=True)
    parser.add_argument("--required-candidate")
    parser.add_argument("--minimum-informative-pairs", type=int, required=True)
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/PEC_ABLATION_CURRENT.json")
    args = parser.parse_args()
    if args.minimum_informative_pairs < 1:
        raise SystemExit("minimum informative pairs must be positive")
    baseline_name, baseline_path = args.baseline
    baseline_raw = json.loads(baseline_path.read_text())
    baseline_rows, baseline_binding = _rows(baseline_raw), _binding(baseline_raw)
    binding_complete = all(value for value in baseline_binding)
    comparisons, binding_failures = _compare_candidates(
        args.candidate, baseline_rows, baseline_binding, args.minimum_informative_pairs
    )
    required = args.required_candidate or (args.candidate[0][0] if len(args.candidate) == 1 else "")
    required_status = str(comparisons.get(required, {}).get("status", "UNKNOWN")) if required else "UNKNOWN"
    status = (
        "FAIL" if binding_failures or required_status == "FAIL"
        else "PASS" if binding_complete and required_status == "PASS"
        else "UNKNOWN"
    )
    report = receipt("pec_ablation", {
        "status": status, "baseline": baseline_name, "baseline_sha256": sha256_file(baseline_path),
        "binding": dict(zip(BINDING_KEYS, baseline_binding, strict=True)),
        "binding_completeness": "PASS" if binding_complete else "UNKNOWN",
        "required_candidate": required, "minimum_informative_pairs": args.minimum_informative_pairs,
        "binding_failures": binding_failures, "comparisons": comparisons,
    })
    write_json(args.out, report); print(json.dumps(report, indent=2))
    return 0 if status == "PASS" or (status == "UNKNOWN" and not args.release_gate) else 1
