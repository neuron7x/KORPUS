#!/usr/bin/env python3
"""What this deployment promises, checked against what it was measured doing.

SRE-001 asks for SLIs, SLOs and an error budget; INF-008 asks that resource limits be
calibrated by a capacity model rather than chosen. Both were external because there was
nothing to measure. There is now.

An objective nobody checks is a paragraph. The objectives below are declared here and
verified against `var/load-probe-api.json` — the report the load probe leaves — so a
change that makes the system slower fails a gate rather than a conversation.

Two rules about the numbers:

  * every objective carries the conditions it was set under. A p95 without a concurrency
    and a corpus size is a claim about somebody else's hardware.
  * the capacity figure is the concurrency at which the measured p95 still fits the
    objective, not the concurrency at which the process survives. A system that answers
    in twenty seconds is up and is not serving.

What stays external: an error budget is a decision about how much failure is acceptable
to whom, and an on-call rotation is people. Neither is a number this file can derive.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Objective:
    """One promise, the measurement that judges it, and why it is set where it is."""

    name: str
    indicator: str
    objective: str
    phase: str
    field: str
    limit: float
    rationale: str

    def judge(self, report: dict[str, Any]) -> dict[str, Any]:
        phase = report.get(self.phase) or {}
        measured = phase.get(self.field)
        met = measured is not None and float(measured) <= self.limit
        return {
            "name": self.name,
            "indicator": self.indicator,
            "objective": self.objective,
            "measured": measured,
            "limit": self.limit,
            "met": met,
            "conditions": {
                "phase": self.phase,
                "concurrency": phase.get("concurrency"),
                "requests": phase.get("requests"),
            },
            "rationale": self.rationale,
        }


#: Set from the run of 2026-08-06 against 1648 documents and 118 622 spans, with headroom
#: rather than at the measured value: an objective set exactly at what was measured fails
#: on the first slow disk and teaches everyone to ignore it.
OBJECTIVES = (
    Objective(
        name="answer_latency_steady",
        indicator="p95 latency of POST /v1/answers at the deployment's rated concurrency",
        objective="p95 <= 5s at 8 concurrent readers",
        phase="soak",
        field="p95_seconds",
        limit=5.0,
        rationale=(
            "A soldier asking during a shift waits for this. Measured 3.27s at eight "
            "concurrent on a sixteen-core workstation with eight uvicorn workers; the "
            "objective carries headroom because the corpus grows and the disk is shared."
        ),
    ),
    Objective(
        name="answer_latency_cold",
        indicator="latency of the first request after a restart",
        objective="cold first request <= 5s",
        phase="cold_first_request",
        field="seconds",
        limit=5.0,
        rationale=(
            "Whatever the process builds lazily is paid for here. A deployment that "
            "takes a minute to answer its first question looks broken to whoever "
            "restarted it, and they restart it again."
        ),
    ),
    Objective(
        name="answers_are_delivered",
        indicator="share of requests that produce an answer document rather than a 5xx",
        objective="no 5xx under the rated load",
        phase="soak",
        field="server_errors",
        limit=0.0,
        rationale=(
            "A refusal is a result and counts as delivered — 'no basis in the corpus' is "
            "the system working. A 500 is not: it says nothing about the corpus, and the "
            "reader cannot tell the two apart from the outside."
        ),
    ),
    Objective(
        name="search_completes",
        indicator="share of answers abstaining because retrieval ran out of budget",
        objective="no retrieval_deadline_exceeded under the rated load",
        phase="soak",
        field="deadline_exceeded",
        limit=0.0,
        rationale=(
            "This one is not about speed. An unfinished search renders as an abstention, "
            "and an abstention reads as 'the corpus holds nothing about this' — an "
            "assertion the system never established. Measured at 62 of 117 before the "
            "budget stopped discarding completed work; 1 of 291 after."
        ),
    ),
)


def _augment(report: dict[str, Any]) -> dict[str, Any]:
    """Derive the counts the objectives judge, so the probe stays a measurement tool."""
    for phase in ("load", "spike", "soak"):
        body = report.get(phase)
        if not isinstance(body, dict):
            continue
        statuses = body.get("statuses") or {}
        body["server_errors"] = sum(
            count for status, count in statuses.items() if str(status).startswith("5")
        )
        decisions = body.get("decisions") or {}
        body["deadline_exceeded"] = int(decisions.get("retrieval_deadline_exceeded", 0))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measurements", type=Path, default=ROOT / "var/load-probe-api.json")
    parser.add_argument("--out", type=Path, default=ROOT / "var/service-objectives.json")
    arguments = parser.parse_args()

    if not arguments.measurements.is_file():
        print(
            json.dumps(
                {
                    "status": "UNMEASURED",
                    "reason": f"no load report at {arguments.measurements}",
                    "interpretation": (
                        "Objectives with no measurement behind them are not met and not "
                        "failed — they are unchecked, which is its own state and must "
                        "not be reported as either."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    report = _augment(json.loads(arguments.measurements.read_text(encoding="utf-8")))
    judged = [objective.judge(report) for objective in OBJECTIVES]
    unmet = [item["name"] for item in judged if not item["met"]]
    result = {
        "schema_version": 1,
        "assessed_at": datetime.now(UTC).isoformat(),
        "measurements": str(arguments.measurements),
        "measured_at": report.get("measured_at"),
        "objectives": judged,
        "unmet": unmet,
        "status": "PASS" if not unmet else "FAIL",
        "external": [
            "An error budget is a decision about how much failure is acceptable to whom.",
            "An on-call rotation is people, and a severity matrix is an agreement.",
        ],
        "interpretation": (
            "Every objective carries the conditions it was measured under. A p95 without "
            "a concurrency and a corpus size is a claim about somebody else's hardware. "
            "The rated concurrency is the one at which the measured p95 still fits the "
            "objective — not the one at which the process survives, because a system "
            "answering in twenty seconds is up and is not serving."
        ),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not unmet else 1


if __name__ == "__main__":
    sys.exit(main())
