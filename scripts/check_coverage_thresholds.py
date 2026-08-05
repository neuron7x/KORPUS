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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config/operations/reference-v5.json"
COVERAGE = ROOT / "var/coverage.json"


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

    statements = int(totals["num_statements"])
    branches = int(totals["num_branches"])
    if statements == 0 or branches == 0:
        # A report over nothing satisfies any ratio. This is the same defect the
        # assurance aggregator had with tests="0" (ADR-0008): outcome without execution.
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "reason": "coverage report measured no statements or no branches",
                    "num_statements": statements,
                    "num_branches": branches,
                },
                indent=2,
            )
        )
        return 1

    measured = {
        "line": int(totals["covered_lines"]) / statements,
        "branch": int(totals["covered_branches"]) / branches,
    }
    minimums = {
        "line": float(policy["minimum_line_rate"]),
        "branch": float(policy["minimum_branch_rate"]),
    }
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
