"""Current source-run evidence; frozen release artifacts are a different subject."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from korpus.application.operations import OperationalReleaseGate
from korpus.application.provenance import compute_source_digest

from scripts.check_evidence_freshness import evaluate as freshness
from scripts.check_mutation_report_freshness import catalogue_ids
from scripts.check_mutation_report_freshness import problems as mutation_problems
from scripts.current_truth_aliases import alias_checks
from scripts.current_truth_contract import load_object, scope_agrees
from scripts.release_identity import release_tag
from scripts.verify_production_hard_predicates import (
    SOURCE_CHECKOUT,
    context_problem,
    evidence_surface,
)

STATIC_REPORTS = (
    "var/dependency-lock-report.json",
    "var/standards-control-map-verification.json",
)
REPORT_PATHS = {
    "eval": "var/eval-report.json",
    "mutation": "var/mutation-report.json",
    "migration": "var/migration-report.json",
    "scale": "var/scale-report.json",
}


def _static_checks(root: Path, release: str, digest: str) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for relative in STATIC_REPORTS:
        path = root / relative
        checks[f"{relative}.present"] = path.is_file()
        if not path.is_file():
            continue
        payload = load_object(path)
        checks[f"{relative}.source_bound"] = (
            scope_agrees(payload) and payload.get("source_tree_sha256") == digest
        )
        checks[f"{relative}.release_bound"] = payload.get("release") == release
        checks[f"{relative}.status_pass"] = payload.get("status") == "PASS"
    return checks


def _assurance_checks(root: Path, digest: str) -> dict[str, bool]:
    paths = {name: root / relative for name, relative in REPORT_PATHS.items()}
    checks = {"assurance.current_inputs": freshness(root)["status"] == "PASS"}
    if not all(path.is_file() for path in paths.values()):
        return checks | {"assurance.reports_present": False}
    reports = {name: load_object(path) for name, path in paths.items()}
    checks["mutation.current_catalogue_and_outcomes"] = not mutation_problems(
        reports["mutation"], catalogue_ids(), digest
    )
    gate = OperationalReleaseGate.load(
        root / "config/operations/reference-v5.json",
        root / "config/operations/admission-grounds.json",
        root,
    ).evaluate(reports, paths, source_digest=digest)
    checks["assurance.recomputed_predicates_pass"] = gate.passed
    recorded_path = root / "var/operational-gate.json"
    checks["operational.recorded_result_present"] = recorded_path.is_file()
    if recorded_path.is_file():
        recorded = load_object(recorded_path)
        checks["operational.recorded_verdict_matches"] = recorded.get("status") == gate.status
        checks["operational.recorded_checks_match"] = recorded.get("checks") == dict(gate.checks)
        checks["operational.recorded_inputs_match"] = recorded.get("evidence_sha256") == dict(
            gate.evidence_sha256
        )
    return checks


def evaluate_source(root: Path) -> dict[str, Any]:
    """Recompute engineering predicates over this run, without admitting a release.

    SOURCE_CHECKOUT is refused when production gate evidence is present, matching the
    hard-predicate gate's existing anti-downgrade rule. Full release truth is still
    verified by verify_current_truth's default FULL_SSOT_DISTRIBUTION context.
    """
    root = root.resolve()
    digest, release = compute_source_digest(root), release_tag(root)
    checks: dict[str, bool] = {
        "source_context.no_production_evidence": context_problem(
            SOURCE_CHECKOUT, evidence_surface(root / "var/production")
        )
        is None
    }
    error: str | None = None
    try:
        checks.update(alias_checks(root, release))
        checks.update(_static_checks(root, release, digest))
        checks.update(_assurance_checks(root, digest))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        checks["source_evidence.readable_and_valid"] = False
        error = f"{type(exc).__name__}: {exc}"
    failures = sorted(key for key, ok in checks.items() if not ok)
    return {
        "schema": "korpus.source-evidence-verification.v1",
        "context": SOURCE_CHECKOUT,
        "status": "PASS" if not failures else "FAIL",
        "release": release,
        "source_tree_sha256": digest,
        "production_authorized": False,
        "checks": checks,
        "failures": failures,
        "error": error,
        "interpretation": (
            "Current engineering evidence and static release aliases only. Frozen release "
            "claims, owner decisions and remote clean-room reproduction remain subject to "
            "the separate full distribution current-truth gate."
        ),
    }


def run_context_cli(full_evaluator: Callable[[Path], dict[str, Any]], root: Path) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--context",
        choices=(SOURCE_CHECKOUT, "FULL_SSOT_DISTRIBUTION"),
        default="FULL_SSOT_DISTRIBUTION",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    evaluator = evaluate_source if args.context == SOURCE_CHECKOUT else full_evaluator
    payload = evaluator(root)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        output = args.out if args.out.is_absolute() else root / args.out
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if payload["status"] == "PASS" else 1
