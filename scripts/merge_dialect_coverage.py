#!/usr/bin/env python3
"""Union SQLite/PostgreSQL coverage only when subjects and CI receipts agree."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.coverage_evidence import (  # noqa: E402
    canonical_json_sha256,
    merge_reports,
    same_subject_problem,
    stamp_report,
)
from korpus.application.github_assurance_receipts import (  # noqa: E402
    identity_from_environment,
    receipt_bound,
    same_identity,
    sha256_bytes,
)
from source_digest import source_tree_digest  # noqa: E402


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def same_subject(primary: dict[str, Any], secondary: dict[str, Any]) -> str | None:
    """Compatibility entrypoint used by the subject-boundary tests."""

    return same_subject_problem(primary, secondary)


def merge(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    """Pure merge for tests/local analysis; publication requires canonical receipts."""

    return merge_reports(
        primary,
        secondary,
        input_sha256={
            "sqlite": canonical_json_sha256(primary),
            "postgresql": canonical_json_sha256(secondary),
        },
        receipt_sha256={"sqlite": "0" * 64, "postgresql": "0" * 64},
        run_identity={"provider": "local-unbound"},
    )


def _receipt_subject_bound(
    receipt: Mapping[str, Any], report: Mapping[str, Any], report_name: str, dialect: str
) -> bool:
    subjects = receipt.get("subjects")
    subject = subjects.get("coverage") if isinstance(subjects, Mapping) else None
    provenance = report.get("korpus_coverage")
    return (
        isinstance(subject, Mapping)
        and isinstance(provenance, Mapping)
        and subject.get("dialect") == dialect
        and subject.get("report") == report_name
        and subject.get("source_inputs_sha256") == provenance.get("source_inputs_sha256")
        and subject.get("file_structure_sha256") == provenance.get("file_structure_sha256")
    )


def _canonical_inputs(
    primary_path: Path,
    secondary_path: Path,
    primary_receipt_path: Path,
    secondary_receipt_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str], dict[str, str], dict[str, Any]]:
    primary, secondary = _load(primary_path), _load(secondary_path)
    primary_receipt = _load(primary_receipt_path)
    secondary_receipt = _load(secondary_receipt_path)
    primary_bytes, secondary_bytes = primary_path.read_bytes(), secondary_path.read_bytes()
    identity = identity_from_environment()
    source = source_tree_digest("HEAD")
    checks = (
        receipt_bound(
            primary_receipt,
            identity=identity,
            kind="coverage-sqlite",
            job="sqlite-coverage",
            source_tree_sha256=source,
            artifacts={primary_path.name: primary_bytes},
        ),
        receipt_bound(
            secondary_receipt,
            identity=identity,
            kind="coverage-postgresql",
            job="postgres",
            source_tree_sha256=source,
            artifacts={secondary_path.name: secondary_bytes},
        ),
        same_identity(primary_receipt, secondary_receipt),
        _receipt_subject_bound(primary_receipt, primary, primary_path.name, "sqlite"),
        _receipt_subject_bound(secondary_receipt, secondary, secondary_path.name, "postgresql"),
    )
    if not all(checks):
        raise ValueError("coverage input receipt is foreign, stale, or byte-divergent")
    return (
        primary,
        secondary,
        {"sqlite": sha256_bytes(primary_bytes), "postgresql": sha256_bytes(secondary_bytes)},
        {
            "sqlite": sha256_bytes(primary_receipt_path.read_bytes()),
            "postgresql": sha256_bytes(secondary_receipt_path.read_bytes()),
        },
        identity,
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, default=ROOT / "var/coverage.json")
    parser.add_argument("--secondary", type=Path, default=ROOT / "var/coverage-postgres.json")
    parser.add_argument(
        "--primary-receipt", type=Path, default=ROOT / "var/coverage-sqlite-receipt.json"
    )
    parser.add_argument(
        "--secondary-receipt",
        type=Path,
        default=ROOT / "var/coverage-postgresql-receipt.json",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "var/coverage-union.json")
    parser.add_argument("--allow-local-unbound", action="store_true")
    return parser.parse_args()


def _local_inputs(
    primary_path: Path, secondary_path: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str], dict[str, str], dict[str, str]]:
    source = source_tree_digest("HEAD")
    primary = stamp_report(
        _load(primary_path), dialect="sqlite", source_tree_sha256=source, root=ROOT
    )
    secondary = stamp_report(
        _load(secondary_path), dialect="postgresql", source_tree_sha256=source, root=ROOT
    )
    inputs = {
        "sqlite": sha256_bytes(primary_path.read_bytes()),
        "postgresql": sha256_bytes(secondary_path.read_bytes()),
    }
    return (
        primary,
        secondary,
        inputs,
        dict.fromkeys(inputs, "0" * 64),
        {"provider": "local-unbound"},
    )


def _write_result(path: Path, merged: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, ensure_ascii=False) + "\n", encoding="utf-8")
    totals = merged["totals"]
    result = {
        "schema": merged["dialect_union"]["schema"],
        "status": "PASS",
        "out": str(path.relative_to(ROOT)),
        "missing_branches": totals["missing_branches"],
        "branch_rate": round(totals["covered_branches"] / totals["num_branches"], 6),
        "statement_rate": round(totals["covered_lines"] / totals["num_statements"], 6),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    args = _arguments()
    reports = (args.primary, args.secondary)
    receipts_paths = (args.primary_receipt, args.secondary_receipt)
    required = reports if args.allow_local_unbound else (*reports, *receipts_paths)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print(json.dumps({"status": "FAIL", "reason": f"missing inputs: {missing}"}))
        return 1
    try:
        if args.allow_local_unbound:
            primary, secondary, inputs, receipts, identity = _local_inputs(*reports)
        else:
            primary, secondary, inputs, receipts, identity = _canonical_inputs(
                *reports, *receipts_paths
            )
        merged = merge_reports(
            primary,
            secondary,
            input_sha256=inputs,
            receipt_sha256=receipts,
            run_identity=identity,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}, ensure_ascii=False))
        return 1
    _write_result(args.out, merged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
