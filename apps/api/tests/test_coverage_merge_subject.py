from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.coverage_evidence import (  # noqa: E402
    canonical_json_sha256,
    coverage_plan_problem,
)
from merge_dialect_coverage import merge, same_subject  # noqa: E402


def _report(
    files: dict[str, tuple[int, int]],
    dialect: str,
    *,
    source: str = "a" * 64,
    inputs: str = "b" * 64,
) -> dict[str, object]:
    entries: dict[str, object] = {}
    for path, (statements, branches) in files.items():
        executed_lines = list(range(1, statements + 1))
        executed_branches = [[index, index + 1] for index in range(1, branches + 1)]
        entries[path] = {
            "executed_lines": executed_lines,
            "missing_lines": [],
            "excluded_lines": [],
            "executed_branches": executed_branches,
            "missing_branches": [],
            "summary": {
                "num_statements": statements,
                "covered_lines": statements,
                "missing_lines": 0,
                "num_branches": branches,
                "covered_branches": branches,
                "missing_branches": 0,
                "num_partial_branches": 0,
            },
        }
    structure = {
        path: {"num_statements": statements, "num_branches": branches}
        for path, (statements, branches) in files.items()
    }
    return {
        "meta": {"format": 3, "version": "7.13.3"},
        "files": entries,
        "totals": {
            "num_statements": sum(value[0] for value in files.values()),
            "covered_lines": sum(value[0] for value in files.values()),
            "missing_lines": 0,
            "num_branches": sum(value[1] for value in files.values()),
            "covered_branches": sum(value[1] for value in files.values()),
            "missing_branches": 0,
            "num_partial_branches": 0,
        },
        "korpus_coverage": {
            "schema": "korpus.coverage-run.v1",
            "dialect": dialect,
            "coverage_schema": 3,
            "digest_scope": "tracked_tree",
            "source_tree_sha256": source,
            "source_inputs_sha256": inputs,
            "file_structure_sha256": canonical_json_sha256(structure),
        },
    }


def _pair(files: dict[str, tuple[int, int]]) -> tuple[dict, dict]:
    return _report(files, "sqlite"), _report(files, "postgresql")


def test_two_runs_of_the_same_tree_are_merged() -> None:
    primary, secondary = _pair({"a.py": (10, 2), "b.py": (4, 0)})
    assert same_subject(primary, secondary) is None
    assert merge(primary, secondary)["dialect_union"]["schema"].endswith(".v2")


def test_a_file_present_in_only_one_run_refuses_the_merge() -> None:
    primary, _ = _pair({"a.py": (10, 2), "b.py": (4, 0)})
    _, secondary = _pair({"a.py": (10, 2)})
    assert same_subject(primary, secondary) is not None


def test_statement_or_branch_count_drift_refuses_the_merge() -> None:
    primary, _ = _pair({"a.py": (10, 2)})
    _, statement_drift = _pair({"a.py": (11, 2)})
    _, branch_drift = _pair({"a.py": (10, 3)})
    assert same_subject(primary, statement_drift) is not None
    assert same_subject(primary, branch_drift) is not None


def test_same_counts_but_foreign_source_or_input_digest_refuses_the_merge() -> None:
    primary = _report({"a.py": (10, 2)}, "sqlite")
    foreign_source = _report({"a.py": (10, 2)}, "postgresql", source="c" * 64)
    foreign_input = _report({"a.py": (10, 2)}, "postgresql", inputs="d" * 64)
    assert "source_tree_sha256" in str(same_subject(primary, foreign_source))
    assert "source_inputs_sha256" in str(same_subject(primary, foreign_input))


def test_branch_set_mutation_without_matching_summary_is_rejected() -> None:
    primary, secondary = _pair({"a.py": (1, 2)})
    secondary["files"]["a.py"]["missing_branches"] = [[7, 8]]
    assert "summary counts" in str(same_subject(primary, secondary))


def test_unprovenanced_reports_are_not_merge_subjects() -> None:
    primary, secondary = _pair({"a.py": (1, 0)})
    del secondary["korpus_coverage"]
    assert "provenance" in str(same_subject(primary, secondary))


def test_plan_must_bind_union_hash_subject_and_run() -> None:
    primary, secondary = _pair({"a.py": (1, 2)})
    union = merge(primary, secondary)
    union_hash = "e" * 64
    subject = union["korpus_coverage"]
    meta = union["dialect_union"]
    plan = {
        "schema": "korpus.coverage-gap-plan.v3",
        "status": "PASS",
        "coverage_union_sha256": union_hash,
        "coverage_union_schema": meta["schema"],
        "coverage_source_tree_sha256": subject["source_tree_sha256"],
        "coverage_source_inputs_sha256": subject["source_inputs_sha256"],
        "github_run": meta["github_run"],
    }
    assert coverage_plan_problem(plan, union, union_hash) is None
    plan["coverage_source_inputs_sha256"] = "f" * 64
    assert coverage_plan_problem(plan, union, union_hash) == "source inputs"


def test_the_real_dialect_reports_are_accepted_only_after_stamping() -> None:
    primary, secondary = ROOT / "var/coverage.json", ROOT / "var/coverage-postgres.json"
    if not primary.is_file() or not secondary.is_file():
        return
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in (primary, secondary)]
    if all("korpus_coverage" in report for report in reports):
        assert same_subject(*reports) is None
