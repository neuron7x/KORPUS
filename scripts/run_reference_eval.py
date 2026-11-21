#!/usr/bin/env python3
"""Evaluate a verified frozen set against reader-authorized source disclosures.

This measures mechanical evidence integrity and retrieval yield, not semantic truth.
Every source request uses the answer request's API origin, bearer and effective date.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evaluation_http import EvaluationHTTP, InvalidEvidence, MeasurementUnavailable
from reference_eval_judge import judge as _judge
from reference_eval_metrics import retrieval_effectiveness  # noqa: F401 (public helper)
from reference_eval_report import reference_report
from reference_eval_set import load_reference_set

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = {"given_name": "Еталон", "family_name": "Тестенко", "specialty": "перевірка"}
RETRY_ON_BUSY = 2
BUSY_BACKOFF_SECONDS = 1.5


def _ask(client: EvaluationHTTP, case: dict[str, Any]) -> dict[str, Any]:
    payload = {"text": case["query"], "declaration": DECLARATION, "as_of": case["as_of"]}
    for attempt in range(RETRY_ON_BUSY + 1):
        try:
            return client.ask(payload)
        except MeasurementUnavailable as exc:
            if str(exc) != "http_429" or attempt == RETRY_ON_BUSY:
                raise
            time.sleep(BUSY_BACKOFF_SECONDS * (attempt + 1))
    raise MeasurementUnavailable("http_429")


def evaluate_case(
    client: EvaluationHTTP, case: dict[str, Any], default_as_of: str
) -> dict[str, Any]:
    effective = {**case, "as_of": case.get("as_of", default_as_of)}
    try:
        answer = _ask(client, effective)
    except (InvalidEvidence, MeasurementUnavailable) as exc:
        missing = isinstance(exc, MeasurementUnavailable)
        return {
            "id": case["id"],
            "kind": case["kind"],
            "stratum": case["stratum"],
            "status": str(exc) if missing else "invalid_response",
            "citations": 0,
            "passed": None if missing else False,
            "unavailable": missing,
            "reasons": [str(exc)],
        }
    return _judge(effective, answer, lambda span_id: client.span(span_id, effective["as_of"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default="")
    parser.add_argument("--set", type=Path, default=ROOT / "evals/datasets/reference.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "var/reference-eval.json")
    parser.add_argument("--timeout", type=float, default=60.0)
    arguments = parser.parse_args()
    try:
        # All input admission, including the complete digest, precedes the first HTTP call.
        meta, cases = load_reference_set(arguments.set)
        default_as_of = datetime.now(UTC).date().isoformat()
        with EvaluationHTTP(arguments.base, arguments.token, arguments.timeout) as client:
            results = [evaluate_case(client, case, default_as_of) for case in cases]
        report = reference_report(results, meta, arguments.base, default_as_of)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        return 2
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "by_stratum"},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
