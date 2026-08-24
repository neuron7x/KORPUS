#!/usr/bin/env python3
"""Enforce the coverage thresholds the release policy states, where they are measured.

`--cov-fail-under` bounds one number: the combined line-and-branch percentage. The
release policy states two, separately — `minimum_line_rate` and `minimum_branch_rate` —
and the aggregator that reads them runs in `source:package`, at the end of the
pipeline, from artefacts produced four stages earlier.

So `coverage_branch` could only ever fail after everything else had already passed,
and on 2026-08-05 it did: branch coverage had been 0.7057 against a policy of 0.75 for
as long as anyone had been writing tests, and nothing said so because the job that
computes the predicate had never run.

Thresholds are read from the policy rather than repeated here. A second copy is a
second thing to forget: the Makefile and the CI job would drift from the aggregator,
and the drift would look like a passing build.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
from korpus.application.release_numeric import coverage_policy_rate, coverage_rates  # noqa: E402

POLICY = ROOT / "config/operations/reference-v5.json"
COVERAGE = ROOT / "var/coverage.json"


def _unit_rate(value: object) -> float:
    return coverage_policy_rate(value, "coverage policy rate")


def main() -> int:
    if not COVERAGE.is_file():
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "reason": f"{COVERAGE.relative_to(ROOT)} is absent; run pytest with "
                    "--cov-report=json before this check",
                },
                indent=2,
            )
        )
        return 1
    policy = json.loads(POLICY.read_text(encoding="utf-8"))["assurance"]
    totals = json.loads(COVERAGE.read_text(encoding="utf-8"))["totals"]

    try:
        line_rate, branch_rate = coverage_rates(totals)
        measured = {"line": line_rate, "branch": branch_rate}
        minimums = {
            "line": coverage_policy_rate(policy["minimum_line_rate"], "minimum_line_rate"),
            "branch": coverage_policy_rate(policy["minimum_branch_rate"], "minimum_branch_rate"),
        }
    except (KeyError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, indent=2))
        return 1
    failures = [
        f"{name} coverage {measured[name]:.4f} is below the policy minimum {minimums[name]}"
        for name in sorted(measured)
        if measured[name] < minimums[name]
    ]
    report = {
        "status": "FAIL" if failures else "PASS",
        "measured": {name: round(value, 4) for name, value in measured.items()},
        "minimum": minimums,
        "policy": str(POLICY.relative_to(ROOT)),
        "failures": failures,
    }
    print(json.dumps(report, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
