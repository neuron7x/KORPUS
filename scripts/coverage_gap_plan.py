#!/usr/bin/env python3
"""Deterministically prioritize remaining coverage gaps by branch count and risk.

This is the adaptive part of the test loop: measured uncovered branch edges become the
next work queue. The algorithm is deterministic, source-relative, and policy-bound; it
never lowers the threshold or excludes code to make the number move.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT)]

from korpus.application.coverage_policy import relative_source_path, risk_weight  # noqa: E402
from korpus.application.numeric_contracts import require_count  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from korpus.application.release_numeric import (  # noqa: E402
    coverage_policy_rate,
    coverage_rates,
    risk_weight_value,
)

from scripts.release_identity import release_tag  # noqa: E402

POLICY = ROOT / "config/operations/test-adaptation-policy.json"


def build_plan(coverage: dict[str, Any], policy: dict[str, Any], root: Path) -> dict[str, Any]:
    totals = coverage["totals"]
    files: list[dict[str, Any]] = []
    weights = {str(k): risk_weight_value(v) for k, v in policy.get("risk_weights", {}).items()}
    for filename, payload in coverage.get("files", {}).items():
        summary = payload.get("summary", {})
        missing = require_count(summary.get("missing_branches", 0))
        if missing <= 0:
            continue
        relative = relative_source_path(str(filename))
        risk = risk_weight(relative, weights)
        files.append(
            {
                "path": relative,
                "missing_branches": missing,
                "branch_rate": round(
                    coverage_policy_rate(
                        float(summary.get("percent_branches_covered", 0.0)) / 100.0, "branch_rate"
                    ),
                    6,
                ),
                "risk_weight": risk,
                "priority": round(missing * risk, 6),
            }
        )
    files.sort(key=lambda item: (-item["priority"], -item["missing_branches"], item["path"]))
    statement_rate, branch_rate = coverage_rates(totals)
    minimum = policy["coverage"]
    minimum_statement_rate = coverage_policy_rate(
        minimum["minimum_statement_rate"], "minimum_statement_rate"
    )
    minimum_branch_rate = coverage_policy_rate(
        minimum["minimum_branch_rate"], "minimum_branch_rate"
    )
    missing_branches = require_count(totals["missing_branches"])
    baseline_missing = require_count(minimum["baseline_missing_branches"])
    maximum_regression = require_count(minimum.get("maximum_missing_branch_regression", 0))
    missing_ceiling = baseline_missing + maximum_regression
    passed = (
        statement_rate >= minimum_statement_rate
        and branch_rate >= minimum_branch_rate
        and missing_branches <= missing_ceiling
    )
    return {
        "schema": "korpus.coverage-gap-plan.v2",
        "status": "PASS" if passed else "FAIL",
        "release": release_tag(),
        "source_tree_sha256": compute_source_digest(root),
        "statement_rate": round(statement_rate, 8),
        "branch_rate": round(branch_rate, 8),
        "minimum_statement_rate": minimum_statement_rate,
        "minimum_branch_rate": minimum_branch_rate,
        "remaining_missing_branches": missing_branches,
        "missing_branch_ceiling": missing_ceiling,
        "missing_branch_regression": missing_branches - baseline_missing,
        "priority_queue": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", type=Path, default=ROOT / "var/coverage.json")
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument("--out", type=Path, default=ROOT / "var/coverage-gap-plan.json")
    args = parser.parse_args()
    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    report = build_plan(coverage, policy, ROOT)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
