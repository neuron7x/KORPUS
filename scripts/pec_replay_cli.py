#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from pec_common import read_jsonl, receipt, sha256_file, write_json
from pec_replay_run import (
    collect_observations,
    coverage_issues,
    replay_status,
    validate_actions,
    validate_observations,
)
from pec_replay_validation import record_issues

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACTIONS = (
    "STOP_USE_CURRENT_EVIDENCE",
    "PLAN_QUERY_VARIANTS",
    "ENABLE_SEMANTIC_RETRIEVAL",
    "PLAN_AND_SEMANTIC",
    "ABSTAIN",
)
REQUIRED_OBSERVATION_FIELDS = (
    "state_fingerprint",
    "features",
    "authorization_ok",
    "answer_error",
    "quality_ok",
    "answer_status",
    "gold_hit",
    "latency_ms",
    "search_count",
    "planner_calls",
    "semantic_calls",
    "candidate_count",
)


def execute(runner: Path, row: dict[str, object], action: str, timeout: float) -> dict[str, object]:
    env = {**os.environ, "PEC_ACTION": action}
    proc = subprocess.run(
        [str(runner)],
        input=(json.dumps(row, ensure_ascii=False) + "\n").encode(),
        capture_output=True,
        env=env,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"runner exit {proc.returncode}: {proc.stderr.decode(errors='replace')[:500]}"
        )
    value = json.loads(proc.stdout)
    if not isinstance(value, dict):
        raise TypeError("replay runner must emit one JSON object")
    value.update({"query_id": row["id"], "group_id": row["group_id"], "action": action})
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--runner", type=Path)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--actions", default=",".join(DEFAULT_ACTIONS))
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--corpus-release-id")
    parser.add_argument("--answer-calibration-id")
    parser.add_argument("--evaluation-protocol", type=Path)
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "reports/PEC_COUNTERFACTUAL_REPLAY_CURRENT.json"
    )
    args = parser.parse_args()

    dataset = read_jsonl(args.dataset)
    dataset_by_id = {str(row["id"]): row for row in dataset}
    actions = tuple(value for value in args.actions.split(",") if value)
    errors = validate_actions(actions, DEFAULT_ACTIONS)
    observations, execution_errors = collect_observations(
        args, dataset, actions, read_jsonl, execute
    )
    errors.extend(execution_errors)
    expected_protocol_sha256 = (
        sha256_file(args.evaluation_protocol) if args.evaluation_protocol else None
    )
    binding_inputs_complete = bool(
        args.corpus_release_id and args.answer_calibration_id and expected_protocol_sha256
    )
    if args.release_gate and not binding_inputs_complete:
        errors.append(
            "release_gate_requires_corpus_release_answer_calibration_and_evaluation_protocol"
        )
    validation_issues = validate_observations(
        observations,
        record_issues=record_issues,
        dataset_by_id=dataset_by_id,
        actions=actions,
        expected_corpus_release_id=args.corpus_release_id,
        expected_protocol_sha256=expected_protocol_sha256,
        expected_answer_calibration_id=args.answer_calibration_id,
        require_bindings=binding_inputs_complete,
    )
    missing, coverage_validation = coverage_issues(dataset, actions, observations)
    validation_issues.extend(coverage_validation)
    status = replay_status(errors, missing, validation_issues, binding_inputs_complete)

    report = receipt(
        "pec_counterfactual_replay",
        {
            "status": status,
            "dataset_sha256": sha256_file(args.dataset),
            "corpus_release_id": args.corpus_release_id or "",
            "evaluation_protocol_sha256": expected_protocol_sha256 or "",
            "answer_calibration_id": args.answer_calibration_id or "",
            "binding_completeness": "PASS" if binding_inputs_complete else "UNKNOWN",
            "queries": len(dataset),
            "actions": list(actions),
            "observations": observations,
            "missing": missing[:100],
            "validation_issues": validation_issues[:100],
            "errors": errors[:100],
        },
    )
    write_json(args.out, report)
    print(
        json.dumps({key: value for key, value in report.items() if key != "observations"}, indent=2)
    )
    return 0 if status == "PASS" or (status == "UNKNOWN" and not args.release_gate) else 1
