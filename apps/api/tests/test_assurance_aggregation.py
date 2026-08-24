"""The aggregator must not call an unexecuted run successful.

Destruction stage 2026-08-03: a JUnit report with ``tests="0"`` produced
``checks.pytest = true`` — nothing had failed because nothing had run. The same
report declared ruff and mypy "NOT_EXECUTED" and still read PASS.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from korpus.application.assurance import evaluate_assurance
from korpus.application.provenance import PROVENANCE_KEY

POLICY = json.loads(Path("config/operations/reference-v5.json").read_text(encoding="utf-8"))
DIGEST = "d" * 64


def provenance() -> dict:
    return {
        "schema_version": 1,
        "source_digest": DIGEST,
        "generator": "test",
        "generated_at": "2026-08-04T00:00:00+00:00",
    }


def junit(tests: int = 273, failures: int = 0, errors: int = 0, skipped: int = 1) -> dict:
    return {
        "tests": str(tests),
        "failures": str(failures),
        "errors": str(errors),
        "skipped": str(skipped),
        "time": "24.0",
    }


def coverage(line: float = 0.96, branch: float = 0.91) -> dict:
    return {"line-rate": str(line), "branch-rate": str(branch)}


def reports() -> dict:
    return {
        "eval": {"pass_rate": 1.0, PROVENANCE_KEY: provenance()},
        "mutation": {"mutation_score_over_catalogue": 1.0, PROVENANCE_KEY: provenance()},
        "migration": {"table_set_match": True, PROVENANCE_KEY: provenance()},
        "scale": {"status": "PASS", PROVENANCE_KEY: provenance()},
        "operational": {"status": "PASS"},
        # A release with no rehearsed restore is a release nobody has asked the
        # question of. Every assembly before 2026-08-05 ran without this key.
        "recovery": {
            "scale_class": "ci-fixture",
            "rto_seconds": 12.5,
            "rpo_seconds": 0.0,
            "lost_events": 0,
            "provenance": {
                "backup_bytes": 40960,
                "plaintext_bytes": 131072,
                "document_rows": 2,
                "audit_event_rows": 7,
                "engine_version": "170004",
                "measured_at": "2026-08-05T09:00:00+00:00",
                "writes_after_backup": 5,
            },
        },
    }


def quality(ruff: str = "PASS", mypy: str = "PASS") -> dict:
    return {
        "status": "PASS" if ruff == mypy == "PASS" else "FAIL",
        "tools": {
            "ruff": {"status": ruff, "exit_code": 0 if ruff == "PASS" else 1, "violations": 0},
            "mypy": {"status": mypy, "exit_code": 0 if mypy == "PASS" else 1},
        },
    }


def evaluate(**overrides):
    arguments = {
        "policy": POLICY,
        "junit": junit(),
        "coverage": coverage(),
        "reports": reports(),
        "quality": quality(),
        "source_digest": DIGEST,
    }
    arguments.update(overrides)
    return evaluate_assurance(**arguments)


def test_complete_evidence_reaches_pass() -> None:
    result = evaluate()
    assert result.passed is True, result.failures


def test_zero_tests_is_not_a_successful_run() -> None:
    result = evaluate(junit=junit(tests=0, skipped=0))
    assert result.passed is False
    assert result.checks["tests_executed"] is False
    # The historic bug: outcome alone still looks clean.
    assert result.checks["tests_outcome"] is True


def test_a_suite_that_skipped_almost_everything_is_not_a_run() -> None:
    result = evaluate(junit=junit(tests=273, skipped=272))
    assert result.passed is False
    assert result.checks["tests_not_mostly_skipped"] is False


def test_failing_tests_fail_the_aggregate() -> None:
    result = evaluate(junit=junit(failures=1))
    assert result.passed is False
    assert result.checks["tests_outcome"] is False


def test_errored_tests_fail_the_aggregate() -> None:
    result = evaluate(junit=junit(errors=1))
    assert result.passed is False
    assert result.checks["tests_outcome"] is False


def test_unparsable_test_count_is_not_treated_as_success() -> None:
    result = evaluate(junit={"tests": "many", "failures": "0", "errors": "0", "skipped": "0"})
    assert result.passed is False
    assert result.checks["tests_executed"] is False


@pytest.mark.parametrize("line,branch", [(0.5, 0.91), (0.96, 0.10)])
def test_coverage_below_policy_fails(line: float, branch: float) -> None:
    result = evaluate(coverage=coverage(line=line, branch=branch))
    assert result.passed is False


@pytest.mark.parametrize("tool", ["ruff", "mypy"])
def test_a_quality_tool_that_did_not_pass_fails_the_aggregate(tool: str) -> None:
    result = evaluate(quality=quality(**{tool: "FAIL"}))
    assert result.passed is False
    assert result.checks["quality_tooling_executed"] is False


def test_absent_quality_evidence_is_a_failure_not_a_pass() -> None:
    assert evaluate(quality=None).checks["quality_tooling_executed"] is False
    assert evaluate(quality={}).checks["quality_tooling_executed"] is False
    assert evaluate(quality={"tools": {}}).checks["quality_tooling_executed"] is False


def test_declared_but_unexecuted_tooling_cannot_pass() -> None:
    """The exact historic payload: a string where a run should be."""

    result = evaluate(
        quality={
            "tools": {
                "ruff": "NOT_EXECUTED_LOCAL_PACKAGE_UNAVAILABLE; REQUIRED_IN_GITLAB",
                "mypy": "NOT_EXECUTED_LOCAL_PACKAGE_UNAVAILABLE; REQUIRED_IN_GITLAB",
            }
        }
    )
    assert result.passed is False
    assert result.checks["quality_tooling_executed"] is False


def test_a_tool_reporting_pass_with_a_nonzero_exit_code_is_rejected() -> None:
    broken = quality()
    broken["tools"]["ruff"]["exit_code"] = 2
    result = evaluate(quality=broken)
    assert result.checks["quality_tooling_executed"] is False


def test_evidence_from_a_foreign_tree_fails_the_aggregate() -> None:
    result = evaluate(source_digest="e" * 64)
    assert result.passed is False
    assert result.checks["evidence_provenance"] is False


def test_missing_gate_reports_fail_the_aggregate() -> None:
    incomplete = reports()
    del incomplete["mutation"]
    result = evaluate(reports=incomplete)
    assert result.passed is False
    assert result.checks["reports_present"] is False


def test_mutation_score_over_catalogue_is_the_measured_quantity() -> None:
    shrunk = reports()
    shrunk["mutation"] = {
        "mutation_score": 1.0,
        "mutation_score_over_catalogue": 0.9,
        PROVENANCE_KEY: provenance(),
    }
    result = evaluate(reports=shrunk)
    assert result.passed is False
    assert result.checks["mutation"] is False


@pytest.mark.parametrize("impossible", [float("nan"), float("inf"), -0.01, 1.01])
def test_non_probability_coverage_cannot_satisfy_release_threshold(impossible: float) -> None:
    result = evaluate(coverage={"line-rate": impossible, "branch-rate": 0.91})
    assert result.passed is False
    assert result.checks["coverage_line"] is False


def test_invalid_coverage_policy_threshold_cannot_make_the_gate_easier() -> None:
    broken = json.loads(json.dumps(POLICY))
    broken["assurance"]["minimum_line_rate"] = float("nan")
    result = evaluate(policy=broken)
    assert result.passed is False
    assert result.checks["coverage_line"] is False
