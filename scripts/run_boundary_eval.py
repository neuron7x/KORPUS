#!/usr/bin/env python3
"""Measure both boundary axes from the exact validated frozen question snapshot.

Counts indicate whether an answer was issued, not whether it was supported or correct.
Dependency/transport failure is UNKNOWN; malformed or refused responses are FAIL.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from boundary_eval_set import load_boundary_set
from evaluation_http import EvaluationHTTP, InvalidEvidence, MeasurementUnavailable
from reference_eval_metrics import ABSTAINED

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/datasets/domain_boundary.jsonl"


def ask(client: EvaluationHTTP, question: str, as_of: str) -> dict[str, Any]:
    for attempt in range(2):
        try:
            payload = client.ask({"text": question, "as_of": as_of})
            status = payload.get("status")
            if not isinstance(status, str) or status not in {"answered", *ABSTAINED}:
                raise InvalidEvidence("unexpected answer status")
            return payload
        except MeasurementUnavailable:
            if attempt == 1:
                raise
            time.sleep(1.0)
    raise MeasurementUnavailable("transport_unavailable")


def _measure(rows: list[dict[str, Any]], client: EvaluationHTTP, as_of: str) -> dict[str, Any]:
    strata: dict[str, dict[str, int]] = {
        "in_corpus": {"answered": 0, "judged": 0},
        "out_of_corpus": {"answered": 0, "judged": 0},
    }
    unreachable: list[str] = []
    invalid: list[str] = []
    for row in rows:
        try:
            payload = ask(client, row["query"], as_of)
        except MeasurementUnavailable:
            unreachable.append(row["id"])
            continue
        except InvalidEvidence:
            invalid.append(row["id"])
            continue
        bucket = strata[row["stratum"]]
        bucket["judged"] += 1
        bucket["answered"] += int(payload["status"] == "answered")
    return {
        "status": _status(invalid, unreachable),
        "unreachable": unreachable,
        "invalid": invalid,
        **{
            key: {
                **bucket,
                "rate": bucket["answered"] / bucket["judged"] if bucket["judged"] else None,
            }
            for key, bucket in strata.items()
        },
    }


def _status(invalid: list[str], unreachable: list[str]) -> str:
    return "FAIL" if invalid else ("UNKNOWN" if unreachable else "MEASURED")


def evaluate(dataset: Path, base: str, token: str, timeout: float) -> dict[str, Any]:
    # Read and bind all rows/metadata before HTTP. Never re-read a mutable file after asking.
    meta, rows = load_boundary_set(dataset)
    as_of = datetime.now(UTC).date().isoformat()
    with EvaluationHTTP(base, token, timeout) as client:
        counts = _measure(rows, client, as_of)
    return {
        "schema": "korpus.domain-boundary-eval.v1",
        "ran_at": datetime.now(UTC).isoformat(),
        "base": base,
        "as_of": as_of,
        "set_digest": meta["digest"],
        **counts,
        "cannot_judge": meta["cannot_judge"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8081/api")
    parser.add_argument("--token", default="")
    parser.add_argument("--set", type=Path, default=DATASET)
    parser.add_argument("--out", type=Path, default=ROOT / "var/boundary-eval.json")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    try:
        report = evaluate(args.set, args.base, args.token, args.timeout)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "MEASURED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
