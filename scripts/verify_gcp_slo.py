#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gcp.slo_contract import evaluate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    predicates = evaluate(args.root)
    payload = {
        "status": "PASS" if all(item.passed for item in predicates) else "FAIL",
        "total": len(predicates),
        "passed": sum(item.passed for item in predicates),
        "predicates": [item.__dict__ for item in predicates],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
