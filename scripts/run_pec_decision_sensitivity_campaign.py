#!/usr/bin/env python3
"""Summarize empirical decision flips and boundary proximity from PEC oracle replay."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from pec_common import receipt, sha256_file, write_json

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/PEC_DECISION_SENSITIVITY_CURRENT.json")
    args = parser.parse_args()
    raw = json.loads(args.oracle.read_text())
    decisions = list(raw.get("decisions", []))
    action_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"samples": 0, "flips": 0, "decision_value": 0})
    stable_baseline = 0
    nonbaseline_without_value = 0
    boundary_distances: list[float] = []
    for decision in decisions:
        stable_baseline += int(decision.get("oracle_reason") == "baseline_decision_already_admissible")
        features = dict(decision.get("features", {}))
        if isinstance(features.get("decision_boundary_distance"), (int, float)):
            boundary_distances.append(float(features["decision_boundary_distance"]))
        for transition in decision.get("decision_transitions", []):
            action = str(transition.get("action", ""))
            state = action_stats[action]
            state["samples"] += 1
            state["flips"] += int(bool(transition.get("decision_changed")))
            state["decision_value"] += int(bool(transition.get("has_decision_value")))
        nonbaseline_without_value += int(
            decision.get("oracle_reason") == "non_baseline_action_without_decision_value"
        )
    status = "PASS" if decisions and nonbaseline_without_value == 0 else ("FAIL" if nonbaseline_without_value else "UNKNOWN")
    report = receipt("pec_decision_sensitivity", {
        "status": status,
        "oracle_sha256": sha256_file(args.oracle),
        "queries": len(decisions),
        "stable_admissible_baseline": stable_baseline,
        "nonbaseline_without_decision_value": nonbaseline_without_value,
        "actions": dict(sorted(action_stats.items())),
        "boundary_distance": {
            "observed": len(boundary_distances),
            "minimum": min(boundary_distances) if boundary_distances else None,
            "maximum": max(boundary_distances) if boundary_distances else None,
            "mean": sum(boundary_distances) / len(boundary_distances) if boundary_distances else None,
        },
    })
    write_json(args.out, report)
    print(json.dumps(report, indent=2))
    return 0 if status == "PASS" or (status == "UNKNOWN" and not args.release_gate) else 1


if __name__ == "__main__":
    raise SystemExit(main())
