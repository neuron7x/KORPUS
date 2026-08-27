#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pec_common import read_jsonl, receipt, sha256_file, write_json
from pec_dataset_audit import audit_rows

ROOT = Path(__file__).resolve().parents[1]


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "evals/datasets/pec/pec_eval.jsonl")
    parser.add_argument("--version-inventory", type=Path)
    parser.add_argument("--production-judged", action="store_true")
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/PEC_DATASET_AUDIT_CURRENT.json")
    return parser.parse_args()


def _inventory(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    raw = json.loads(path.read_text())
    values = raw if isinstance(raw, list) else raw.get("version_ids", [])
    return {str(value) for value in values}


def main() -> int:
    args = _arguments()
    rows = read_jsonl(args.dataset)
    inventory = _inventory(args.version_inventory)
    issues, groups, queries = audit_rows(rows, inventory)
    corpus_binding = "PASS" if inventory is not None else "UNKNOWN"
    status = (
        "FAIL"
        if issues
        else ("PASS" if corpus_binding == "PASS" and args.production_judged else "UNKNOWN")
    )
    report = receipt(
        "pec_dataset_audit",
        {
            "status": status,
            "dataset_sha256": sha256_file(args.dataset),
            "rows": len(rows),
            "groups": len(groups),
            "unique_queries": len(queries),
            "production_judged": args.production_judged,
            "corpus_binding": corpus_binding,
            "issues": issues[:100],
        },
    )
    write_json(args.out, report)
    print(json.dumps(report, indent=2))
    return 0 if status == "PASS" or (status == "UNKNOWN" and not args.release_gate) else 1


if __name__ == "__main__":
    raise SystemExit(main())
