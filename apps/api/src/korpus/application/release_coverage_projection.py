"""Admit and project GitHub-bound dialect coverage for release preflight."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from korpus.application.coverage_evidence import coverage_plan_problem, coverage_union_problem
from korpus.application.github_assurance_receipts import (
    admitted_file,
    canonical_identity,
    receipt_bound,
    same_identity,
)


@dataclass(frozen=True)
class CoverageBundle:
    union: dict[str, Any]
    plan: dict[str, Any]
    receipt: dict[str, Any]
    admission: dict[str, Any]
    raw: dict[str, bytes]


def load_coverage_bundle(root: Path) -> CoverageBundle | None:
    directory = root / "var/ci-evidence"
    names = {
        "union": "coverage-union.json",
        "plan": "coverage-gap-plan.json",
        "receipt": "coverage-ci-receipt.json",
        "admission": "assurance-admission.json",
    }
    paths = {key: directory / name for key, name in names.items()}
    if any(not path.is_file() for path in paths.values()):
        return None
    try:
        raw = {name: path.read_bytes() for name, path in paths.items()}
        values = {name: json.loads(payload) for name, payload in raw.items()}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not all(isinstance(value, dict) for value in values.values()):
        return None
    return CoverageBundle(raw=raw, **values)


def coverage_binding_problem(bundle: CoverageBundle, source: str, digest: str) -> str | None:
    union_meta = bundle.union.get("dialect_union")
    union_run = union_meta.get("github_run") if isinstance(union_meta, dict) else None
    plan_run = bundle.plan.get("github_run")
    artifacts = {
        "coverage-union.json": bundle.raw["union"],
        "coverage-gap-plan.json": bundle.raw["plan"],
    }
    checks = {
        "union_structure": coverage_union_problem(bundle.union) is None,
        "canonical_admission": canonical_identity(bundle.admission),
        "producer_receipt": receipt_bound(
            bundle.receipt,
            identity=bundle.admission,
            kind="coverage-union",
            job="coverage-union",
            source_tree_sha256=source,
            artifacts=artifacts,
        ),
        "union_run": isinstance(union_run, dict) and same_identity(union_run, bundle.admission),
        "plan_run": isinstance(plan_run, dict) and same_identity(plan_run, bundle.admission),
        "plan_schema": bundle.plan.get("schema") == "korpus.coverage-gap-plan.v3",
        "plan_pass": bundle.plan.get("status") == "PASS",
        "plan_source": bundle.plan.get("source_tree_sha256") == digest,
        "plan_binding": coverage_plan_problem(
            bundle.plan,
            bundle.union,
            hashlib.sha256(bundle.raw["union"]).hexdigest(),
            evidence_source_sha256=digest,
        )
        is None,
        "plan_union": bundle.plan.get("coverage_union_sha256")
        == hashlib.sha256(bundle.raw["union"]).hexdigest(),
        "import_admission": _all_files_admitted(bundle),
    }
    return next((name for name, passed in checks.items() if not passed), None)


def project_coverage(
    root: Path, digest: str, release: str, source_tree_sha256: str
) -> dict[str, Any] | None:
    bundle = load_coverage_bundle(root)
    if bundle is None or coverage_binding_problem(bundle, source_tree_sha256, digest):
        return None
    totals = bundle.union["totals"]
    statements, branches = totals["num_statements"], totals["num_branches"]
    if not statements or not branches:
        return None
    return {
        "schema": "korpus.coverage-report.v2",
        "status": "PASS",
        "release": release,
        "source_tree_sha256": digest,
        "statement_coverage_percent": round(100.0 * totals["covered_lines"] / statements, 4),
        "branch_coverage_percent": round(100.0 * totals["covered_branches"] / branches, 4),
        "measured_from": "var/ci-evidence/coverage-union.json",
        "ci_receipt_sha256": hashlib.sha256(bundle.raw["receipt"]).hexdigest(),
        "github_run_id": bundle.receipt["run_id"],
        "github_run_attempt": bundle.receipt["run_attempt"],
    }


def _all_files_admitted(bundle: CoverageBundle) -> bool:
    return all(
        admitted_file(
            bundle.admission,
            identity=bundle.admission,
            artifact="coverage-union-evidence",
            name=name,
            payload=payload,
        )
        for name, payload in (
            ("coverage-union.json", bundle.raw["union"]),
            ("coverage-gap-plan.json", bundle.raw["plan"]),
            ("coverage-ci-receipt.json", bundle.raw["receipt"]),
        )
    )
