"""Counterfactual replay execution and completeness helpers."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path


def validate_actions(actions: tuple[str, ...], allowed: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    if len(actions) != len(set(actions)):
        errors.append("duplicate_actions")
    unknown = sorted(set(actions) - set(allowed))
    if unknown:
        errors.append(f"unknown_actions:{','.join(unknown)}")
    return errors


def collect_observations(
    args: argparse.Namespace,
    dataset: list[dict[str, object]],
    actions: tuple[str, ...],
    read_jsonl: Callable[[Path], list[dict[str, object]]],
    execute: Callable[..., dict[str, object]],
) -> tuple[list[dict[str, object]], list[str]]:
    errors: list[str] = []
    if args.observations:
        return read_jsonl(args.observations), errors
    if not args.runner:
        raise SystemExit("--runner or --observations is required")
    observations: list[dict[str, object]] = []
    for row in dataset:
        for action in actions:
            try:
                observations.append(execute(args.runner, row, action, args.timeout))
            except Exception as exc:
                errors.append(f"{row['id']}:{action}:{type(exc).__name__}:{exc}")
    return observations, errors


def coverage_issues(
    dataset: list[dict[str, object]],
    actions: tuple[str, ...],
    observations: list[dict[str, object]],
) -> tuple[list[str], list[str]]:
    coverage = {(str(row.get("query_id")), str(row.get("action"))) for row in observations}
    missing = [
        f"{row['id']}:{action}"
        for row in dataset
        for action in actions
        if (str(row["id"]), action) not in coverage
    ]
    issues: list[str] = []
    duplicates = len(observations) - len(coverage)
    if duplicates:
        issues.append(f"duplicate_query_action_observations:{duplicates}")
    return missing, issues


def replay_status(
    errors: list[str], missing: list[str], validation_issues: list[str], bindings_complete: bool
) -> str:
    if errors or missing or validation_issues:
        return "FAIL"
    return "PASS" if bindings_complete else "UNKNOWN"


def validate_observations(
    observations: list[dict[str, object]],
    *,
    record_issues: Callable[..., list[str]],
    dataset_by_id: dict[str, dict[str, object]],
    actions: tuple[str, ...],
    expected_corpus_release_id: str,
    expected_protocol_sha256: str,
    expected_answer_calibration_id: str,
    require_bindings: bool,
) -> list[str]:
    issues: list[str] = []
    for row in observations:
        issues.extend(
            record_issues(
                row,
                dataset_by_id=dataset_by_id,
                actions=actions,
                expected_corpus_release_id=expected_corpus_release_id,
                expected_protocol_sha256=expected_protocol_sha256,
                expected_answer_calibration_id=expected_answer_calibration_id,
                require_bindings=require_bindings,
            )
        )
    return issues
