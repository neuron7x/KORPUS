"""Structural and provenance invariants for dialect coverage evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

RUN_SCHEMA = "korpus.coverage-run.v1"
UNION_SCHEMA = "korpus.dialect-coverage-union.v2"
SUPPORTED_COVERAGE_FORMAT = 3
_DIALECTS = frozenset({"sqlite", "postgresql"})


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def coverage_structure(report: Mapping[str, Any]) -> dict[str, dict[str, int]] | None:
    files = report.get("files")
    if not isinstance(files, Mapping) or not files:
        return None
    structure: dict[str, dict[str, int]] = {}
    for name, entry in files.items():
        summary = entry.get("summary") if isinstance(entry, Mapping) else None
        if not isinstance(name, str) or not name or not isinstance(summary, Mapping):
            return None
        statements = _count(summary.get("num_statements"))
        branches = _count(summary.get("num_branches"))
        if statements is None or branches is None:
            return None
        structure[name] = {"num_statements": statements, "num_branches": branches}
    return structure


def source_inputs_sha256(report: Mapping[str, Any], root: Path) -> str:
    """Hash exact measured source paths and bytes; refuse missing/out-of-tree inputs."""

    structure = coverage_structure(report)
    if structure is None:
        raise ValueError("coverage report has no valid file structure")
    root = root.resolve()
    hasher = hashlib.sha256()
    for name in sorted(structure):
        candidate = Path(name)
        path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"coverage input escapes repository: {name}")
        if not path.is_file():
            raise ValueError(f"coverage input is absent: {name}")
        relative = path.relative_to(root).as_posix().encode()
        payload = path.read_bytes()
        hasher.update(len(relative).to_bytes(4, "big"))
        hasher.update(relative)
        hasher.update(len(payload).to_bytes(8, "big"))
        hasher.update(payload)
    return hasher.hexdigest()


def stamp_report(
    report: Mapping[str, Any], *, dialect: str, source_tree_sha256: str, root: Path
) -> dict[str, Any]:
    if dialect not in _DIALECTS:
        raise ValueError(f"unsupported coverage dialect: {dialect}")
    problem = coverage_report_problem(report, require_provenance=False)
    if problem is not None:
        raise ValueError(problem)
    stamped: dict[str, Any] = json.loads(json.dumps(report))
    structure = coverage_structure(stamped)
    assert structure is not None
    stamped["korpus_coverage"] = {
        "schema": RUN_SCHEMA,
        "dialect": dialect,
        "coverage_schema": SUPPORTED_COVERAGE_FORMAT,
        "digest_scope": "tracked_tree",
        "source_tree_sha256": source_tree_sha256,
        "source_inputs_sha256": source_inputs_sha256(stamped, root),
        "file_structure_sha256": canonical_json_sha256(structure),
    }
    return stamped


def coverage_report_problem(
    report: Mapping[str, Any], *, require_provenance: bool = True
) -> str | None:
    meta = report.get("meta")
    if not isinstance(meta, Mapping) or meta.get("format") != SUPPORTED_COVERAGE_FORMAT:
        return "unsupported coverage.py JSON schema"
    structure = coverage_structure(report)
    if structure is None:
        return "coverage report has no valid files"
    for name, entry in report["files"].items():
        problem = _file_problem(entry)
        if problem is not None:
            return f"{name}: {problem}"
    totals = report.get("totals")
    if not isinstance(totals, Mapping) or not _totals_match(totals, report["files"]):
        return "coverage totals do not equal per-file counts"
    if require_provenance and not _run_provenance(report.get("korpus_coverage"), structure):
        return "coverage run provenance is absent or inconsistent"
    return None


def same_subject_problem(primary: Mapping[str, Any], secondary: Mapping[str, Any]) -> str | None:
    for label, report in (("primary", primary), ("secondary", secondary)):
        if problem := coverage_report_problem(report):
            return f"{label} coverage is invalid: {problem}"
    left = coverage_structure(primary)
    right = coverage_structure(secondary)
    assert left is not None and right is not None
    if set(left) != set(right):
        return "coverage runs contain different file sets"
    shifted = [name for name in left if left[name] != right[name]]
    if shifted:
        return f"coverage runs disagree on statements/branches: {sorted(shifted)[:2]}"
    for name in left:
        first, second = primary["files"][name], secondary["files"][name]
        if set(first["executed_lines"]) | set(first["missing_lines"]) != set(
            second["executed_lines"]
        ) | set(second["missing_lines"]):
            return f"coverage runs disagree on executable lines: {name}"
    left_subject = primary["korpus_coverage"]
    right_subject = secondary["korpus_coverage"]
    for key in (
        "coverage_schema",
        "digest_scope",
        "source_tree_sha256",
        "source_inputs_sha256",
        "file_structure_sha256",
    ):
        if left_subject.get(key) != right_subject.get(key):
            return f"coverage runs disagree on {key}"
    if {left_subject.get("dialect"), right_subject.get("dialect")} != _DIALECTS:
        return "coverage runs do not name the sqlite/postgresql pair"
    return None


def merge_reports(
    primary: Mapping[str, Any],
    secondary: Mapping[str, Any],
    *,
    input_sha256: Mapping[str, str],
    receipt_sha256: Mapping[str, str],
    run_identity: Mapping[str, Any],
) -> dict[str, Any]:
    if problem := same_subject_problem(primary, secondary):
        raise ValueError(problem)
    merged: dict[str, Any] = json.loads(json.dumps(primary))
    for name, entry in merged["files"].items():
        counterpart = secondary["files"][name]
        entry["executed_lines"] = sorted(
            set(entry.get("executed_lines", ())) | set(counterpart.get("executed_lines", ()))
        )
        entry["missing_lines"] = sorted(
            set(entry.get("missing_lines", ())) & set(counterpart.get("missing_lines", ()))
        )
        entry["executed_branches"] = _sorted_arcs(
            _arcs(entry.get("executed_branches")) | _arcs(counterpart.get("executed_branches"))
        )
        entry["missing_branches"] = _sorted_arcs(
            _arcs(entry.get("missing_branches")) & _arcs(counterpart.get("missing_branches"))
        )
        _replace_summary(entry)
    _replace_totals(merged)
    subject = primary["korpus_coverage"]
    merged["korpus_coverage"] = {
        "schema": UNION_SCHEMA,
        "coverage_schema": SUPPORTED_COVERAGE_FORMAT,
        "digest_scope": "tracked_tree",
        "source_tree_sha256": subject["source_tree_sha256"],
        "source_inputs_sha256": subject["source_inputs_sha256"],
        "file_structure_sha256": subject["file_structure_sha256"],
    }
    merged["dialect_union"] = {
        "schema": UNION_SCHEMA,
        "runs": ["sqlite", "postgresql"],
        "input_sha256": dict(input_sha256),
        "input_receipt_sha256": dict(receipt_sha256),
        "github_run": dict(run_identity),
    }
    if problem := coverage_union_problem(merged):
        raise ValueError(problem)
    return merged


def coverage_union_problem(report: Mapping[str, Any]) -> str | None:
    if problem := coverage_report_problem(report, require_provenance=False):
        return problem
    subject = report.get("korpus_coverage")
    union = report.get("dialect_union")
    structure = coverage_structure(report)
    if not isinstance(subject, Mapping) or not isinstance(union, Mapping) or structure is None:
        return "coverage union provenance is absent"
    if (
        subject.get("schema") != UNION_SCHEMA
        or subject.get("coverage_schema") != SUPPORTED_COVERAGE_FORMAT
        or subject.get("digest_scope") != "tracked_tree"
        or subject.get("file_structure_sha256") != canonical_json_sha256(structure)
        or not _digest(subject.get("source_tree_sha256"))
        or not _digest(subject.get("source_inputs_sha256"))
        or union.get("schema") != UNION_SCHEMA
        or union.get("runs") != ["sqlite", "postgresql"]
    ):
        return "coverage union subject is inconsistent"
    for field in ("input_sha256", "input_receipt_sha256"):
        values = union.get(field)
        if not isinstance(values, Mapping) or set(values) != _DIALECTS:
            return f"coverage union {field} is incomplete"
        if not all(_digest(value) for value in values.values()):
            return f"coverage union {field} contains an invalid digest"
    return None


def coverage_plan_problem(
    plan: Mapping[str, Any],
    union: Mapping[str, Any],
    union_sha256: str,
    *,
    evidence_source_sha256: str | None = None,
) -> str | None:
    """Require a PASS plan to describe the exact validated union and its subjects."""

    if problem := coverage_union_problem(union):
        return f"coverage union is invalid: {problem}"
    subject = union["korpus_coverage"]
    union_meta = union["dialect_union"]
    checks = {
        "schema": plan.get("schema") == "korpus.coverage-gap-plan.v3",
        "status": plan.get("status") == "PASS",
        "union hash": plan.get("coverage_union_sha256") == union_sha256,
        "union schema": plan.get("coverage_union_schema") == union_meta["schema"],
        "tracked source": plan.get("coverage_source_tree_sha256") == subject["source_tree_sha256"],
        "source inputs": plan.get("coverage_source_inputs_sha256")
        == subject["source_inputs_sha256"],
        "GitHub run": plan.get("github_run") == union_meta.get("github_run"),
    }
    if evidence_source_sha256 is not None:
        checks["evidence source"] = plan.get("source_tree_sha256") == evidence_source_sha256
    return next((name for name, passed in checks.items() if not passed), None)


def _file_problem(entry: Any) -> str | None:
    if not isinstance(entry, Mapping) or not isinstance(entry.get("summary"), Mapping):
        return "file entry/summary is not an object"
    executed_lines = _integers(entry.get("executed_lines"))
    missing_lines = _integers(entry.get("missing_lines"))
    executed_branches = _arcs_or_none(entry.get("executed_branches"))
    missing_branches = _arcs_or_none(entry.get("missing_branches"))
    if None in (executed_lines, missing_lines, executed_branches, missing_branches):
        return "line or branch sets are malformed/duplicated"
    assert executed_lines is not None and missing_lines is not None
    assert executed_branches is not None and missing_branches is not None
    if executed_lines & missing_lines or executed_branches & missing_branches:
        return "covered and missing sets overlap"
    summary = entry["summary"]
    expected = {
        "num_statements": len(executed_lines | missing_lines),
        "covered_lines": len(executed_lines),
        "missing_lines": len(missing_lines),
        "missing_branches": len(missing_branches),
    }
    if any(_count(summary.get(key)) != value for key, value in expected.items()):
        return "summary counts disagree with exact line/branch sets"
    branches = _count(summary.get("num_branches"))
    covered = _count(summary.get("covered_branches"))
    partial = _count(summary.get("num_partial_branches"))
    if (
        branches is None
        or covered is None
        or partial is None
        or covered + len(missing_branches) != branches
        or len(executed_branches) > covered
        or partial > covered
    ):
        return "branch summary is arithmetically impossible"
    return None


def _run_provenance(value: Any, structure: Mapping[str, Any]) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("schema") == RUN_SCHEMA
        and value.get("dialect") in _DIALECTS
        and value.get("coverage_schema") == SUPPORTED_COVERAGE_FORMAT
        and value.get("digest_scope") == "tracked_tree"
        and _digest(value.get("source_tree_sha256"))
        and _digest(value.get("source_inputs_sha256"))
        and value.get("file_structure_sha256") == canonical_json_sha256(structure)
    )


def _totals_match(totals: Mapping[str, Any], files: Mapping[str, Any]) -> bool:
    for key in (
        "num_statements",
        "covered_lines",
        "missing_lines",
        "num_branches",
        "covered_branches",
        "missing_branches",
        "num_partial_branches",
    ):
        expected = sum(entry["summary"][key] for entry in files.values())
        if _count(totals.get(key)) != expected:
            return False
    return True


def _replace_summary(entry: dict[str, Any]) -> None:
    summary = entry["summary"]
    summary["covered_lines"] = len(entry["executed_lines"])
    summary["missing_lines"] = len(entry["missing_lines"])
    summary["covered_branches"] = summary["num_branches"] - len(entry["missing_branches"])
    summary["missing_branches"] = len(entry["missing_branches"])
    summary["num_partial_branches"] = len(
        {arc[0] for arc in entry["executed_branches"]}
        & {arc[0] for arc in entry["missing_branches"]}
    )
    statements = summary["num_statements"]
    branches = summary["num_branches"]
    summary["percent_covered"] = (
        100.0 * summary["covered_lines"] / statements if statements else 100.0
    )
    summary["percent_covered_display"] = str(round(summary["percent_covered"]))
    summary["percent_branches_covered"] = (
        100.0 * summary["covered_branches"] / branches if branches else 100.0
    )


def _replace_totals(report: dict[str, Any]) -> None:
    totals = report["totals"]
    for key in (
        "covered_lines",
        "missing_lines",
        "covered_branches",
        "missing_branches",
        "num_partial_branches",
    ):
        totals[key] = sum(entry["summary"][key] for entry in report["files"].values())
    statements = totals["num_statements"]
    branches = totals["num_branches"]
    totals["percent_covered"] = (
        100.0 * totals["covered_lines"] / statements if statements else 100.0
    )
    totals["percent_covered_display"] = str(round(totals["percent_covered"]))
    totals["percent_statements_covered"] = totals["percent_covered"]
    totals["percent_branches_covered"] = (
        100.0 * totals["covered_branches"] / branches if branches else 100.0
    )


def _arcs(value: Any) -> set[tuple[int, int]]:
    arcs = _arcs_or_none(value)
    if arcs is None:
        raise ValueError("invalid branch arcs")
    return arcs


def _arcs_or_none(value: Any) -> set[tuple[int, int]] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    result: set[tuple[int, int]] = set()
    for item in value:
        if (
            not isinstance(item, Sequence)
            or isinstance(item, (str, bytes))
            or len(item) != 2
            or any(not isinstance(part, int) or isinstance(part, bool) for part in item)
        ):
            return None
        result.add((item[0], item[1]))
    return result if len(result) == len(value) else None


def _integers(value: Any) -> set[int] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    if any(not isinstance(item, int) or isinstance(item, bool) for item in value):
        return None
    result = set(value)
    return result if len(result) == len(value) else None


def _sorted_arcs(value: set[tuple[int, int]]) -> list[list[int]]:
    return [list(arc) for arc in sorted(value)]


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )
