"""Fail-closed arithmetic shared by release evidence consumers."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from korpus.application.numeric_contracts import bounded_number, exact_one, nonnegative_count, require_count, require_positive_number, require_rate


def coverage_rates(totals: Mapping[str, Any]) -> tuple[float, float]:
    statements = require_count(totals["num_statements"], positive=True, label="num_statements")
    branches = require_count(totals["num_branches"], positive=True, label="num_branches")
    lines = require_count(totals["covered_lines"], label="covered_lines")
    covered = require_count(totals["covered_branches"], label="covered_branches")
    if lines > statements or covered > branches:
        raise ValueError("covered counts cannot exceed measured totals")
    return lines / statements, covered / branches


def preflight_report_pass(name: str, report: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    if name == "backend":
        return nonnegative_count(report.get("failed"), allow_digit_string=True) == 0 and nonnegative_count(report.get("errors"), allow_digit_string=True) == 0
    if name == "coverage":
        statement = bounded_number(report.get("statement_coverage_percent"), 0, 100)
        branch = bounded_number(report.get("branch_coverage_percent"), 0, 100)
        line_floor = bounded_number(policy.get("minimum_line_rate"), 0, 1)
        branch_floor = bounded_number(policy.get("minimum_branch_rate"), 0, 1)
        return None not in (statement, branch, line_floor, branch_floor) and statement >= 100 * line_floor and branch >= 100 * branch_floor
    return report.get("status") == "PASS"


def mutation_checks(report: Mapping[str, Any], source_bound: bool) -> tuple[dict[str, bool], int, int, int]:
    total = nonnegative_count(report.get("mutants")); valid = nonnegative_count(report.get("valid_mutants")); killed = nonnegative_count(report.get("killed"))
    formed = None not in (total, valid, killed) and valid <= total and killed <= valid
    total, valid, killed = total or 0, valid or 0, killed or 0
    checks = {"report_present": bool(report), "source_bound": source_bound, "counts_well_formed": formed,
        "catalogue_nonempty": formed and total > 0,
        "all_mutants_valid": formed and valid == total and not report.get("invalid") and not report.get("errors"),
        "all_valid_mutants_killed": formed and killed == valid and not report.get("survived"),
        "catalogue_score_one": exact_one(report.get("mutation_score_over_catalogue"))}
    return checks, total, valid, killed


def coverage_policy_rate(value: object, label: str) -> float:
    return require_rate(value, label=label)


def risk_weight_value(value: object) -> float:
    return require_positive_number(value, label="risk weight")
