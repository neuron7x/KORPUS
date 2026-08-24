#!/usr/bin/env python3
"""Judge measured load against the same SLO policy used by production assurance."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.service_levels import (  # noqa: E402
    COLD_START_LIMIT_SECONDS,
    STEADY_P95_LIMIT_SECONDS,
    evaluate_load_slos,
)

OBJECTIVES: dict[str, tuple[str, str]] = {
    "load_slo_steady_p95": (
        "answer_latency_steady",
        f"p95 <= {STEADY_P95_LIMIT_SECONDS:g}s at rated load",
    ),
    "load_slo_cold_start": (
        "answer_latency_cold",
        f"cold first request <= {COLD_START_LIMIT_SECONDS:g}s",
    ),
    "load_slo_no_5xx_rated": ("answers_are_delivered", "no 5xx under rated load"),
    "load_slo_no_subject_throttle_rated": (
        "rated_capacity_is_honest",
        "no subject throttling under rated load",
    ),
    "load_slo_no_retrieval_deadline": (
        "search_completes",
        "no retrieval_deadline_exceeded under rated load",
    ),
}


def _objective_rows(report: dict[str, Any], checks: dict[str, bool]) -> list[dict[str, Any]]:
    soak = report.get("soak", {}) if isinstance(report.get("soak"), dict) else {}
    cold = (
        report.get("cold_first_request", {})
        if isinstance(report.get("cold_first_request"), dict)
        else {}
    )
    measured = {
        "load_slo_steady_p95": soak.get("p95_seconds"),
        "load_slo_cold_start": cold.get("seconds"),
        "load_slo_no_5xx_rated": soak.get("statuses", {}),
        "load_slo_no_subject_throttle_rated": soak.get("refusal_reasons", {}),
        "load_slo_no_retrieval_deadline": soak.get("decisions", {}),
    }
    return [
        {
            "name": name,
            "predicate": predicate,
            "objective": objective,
            "measured": measured[predicate],
            "met": checks[predicate],
            "conditions": {
                "phase": "cold_first_request" if predicate == "load_slo_cold_start" else "soak",
                "concurrency": soak.get("concurrency"),
                "requests": soak.get("requests"),
            },
            "rationale": "Shared application SLO policy; provenance is evaluated separately.",
        }
        for predicate, (name, objective) in OBJECTIVES.items()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measurements", type=Path, default=ROOT / "var/load-probe.json")
    parser.add_argument("--out", type=Path, default=ROOT / "var/service-objectives.json")
    args = parser.parse_args()
    if not args.measurements.is_file():
        result = {"status": "UNMEASURED", "reason": f"no load report at {args.measurements}"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    report = json.loads(args.measurements.read_text(encoding="utf-8"))
    checks = evaluate_load_slos(report)
    objectives = _objective_rows(report, checks)
    unmet = [row["name"] for row in objectives if not row["met"]]
    result = {
        "schema_version": 2,
        "assessed_at": datetime.now(UTC).isoformat(),
        "measurements": str(args.measurements),
        "measured_at": report.get("measured_at"),
        "checks": checks,
        "objectives": objectives,
        "unmet": unmet,
        "status": "PASS" if not unmet else "FAIL",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(unmet))


if __name__ == "__main__":
    raise SystemExit(main())
