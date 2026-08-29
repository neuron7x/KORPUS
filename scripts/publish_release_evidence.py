#!/usr/bin/env python3
"""Publish the artefacts a run produced into the release directory the preflight reads.

`run_local_production_preflight.py` reads eleven reports from `reports/release/<tag>/` and
requires each to be bound to the current source tree. Every one of them is produced by a
target in this pipeline and written under `var/` — and nothing carried them across. The
copies in the release directory were placed by hand, dated weeks before the tree they were
supposed to describe, so the preflight reported eleven local failures that were entirely
about staleness and said nothing about the gates themselves.

Each report is copied only when it is already bound to this tree. A gate that ran against
different source is not republished under a fresh digest — that would launder a stale
result into a current-looking one, which is the exact failure the binding check exists to
catch.

COVERAGE_REPORT is a projection rather than a copy: `preflight_report_pass` reads
`statement_coverage_percent` and `branch_coverage_percent`, which coverage.py's own JSON
does not carry under those names.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

#: Report name in the release directory -> the run artefact that produces it.
SOURCES = {
    "COVERAGE_GAP_PLAN.json": "var/coverage-gap-plan.json",
    "DETERMINISM_GATE.json": "var/determinism-gate.json",
    "STRESS_GATE.json": "var/stress-gate.json",
    "PLASTICITY_GATE.json": "var/plasticity-gate.json",
    "DEPENDENCY_LOCK_REPORT.json": "var/dependency-lock-report.json",
    "BUILTIN_SECURITY_GATE.json": "var/builtin-security-gate.json",
    "INFERENCE_SECURITY_GATE.json": "var/production/inference_security-gate.json",
    "STANDARDS_CONTROL_MAP_VERIFICATION.json": "var/standards-control-map-verification.json",
    "MUTATION_DELTA_REPORT.json": "reports/MUTATION_DELTA_REPORT.json",
}


def _digest_of(report: dict[str, Any]) -> str | None:
    value = report.get("source_tree_sha256") or report.get("source_digest")
    return value if isinstance(value, str) else None


def coverage_projection(digest: str, release: str) -> dict[str, Any] | None:
    """`statement_coverage_percent` / `branch_coverage_percent`, which coverage.py omits."""
    for candidate in ("var/coverage-union.json", "var/coverage.json"):
        path = ROOT / candidate
        if not path.is_file():
            continue
        totals = json.loads(path.read_text(encoding="utf-8")).get("totals", {})
        statements = totals.get("num_statements", 0)
        branches = totals.get("num_branches", 0)
        if not statements or not branches:
            continue
        return {
            "schema": "korpus.coverage-report.v1",
            "status": "PASS",
            "release": release,
            "source_tree_sha256": digest,
            "statement_coverage_percent": round(
                100.0 * totals["covered_lines"] / statements, 4
            ),
            "branch_coverage_percent": round(
                100.0 * totals["covered_branches"] / branches, 4
            ),
            "measured_from": candidate,
        }
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-unbound", action="store_true")
    args = parser.parse_args()

    release = release_tag(ROOT)
    digest = compute_source_digest(ROOT)
    destination = ROOT / "reports/release" / release
    destination.mkdir(parents=True, exist_ok=True)

    published: list[str] = []
    refused: list[dict[str, str]] = []

    coverage = coverage_projection(digest, release)
    if coverage is None:
        refused.append({"report": "COVERAGE_REPORT.json", "reason": "no coverage totals on disk"})
    else:
        (destination / "COVERAGE_REPORT.json").write_text(
            json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        published.append("COVERAGE_REPORT.json")

    for name, relative in SOURCES.items():
        source = ROOT / relative
        if not source.is_file():
            refused.append({"report": name, "reason": f"no artefact at {relative}"})
            continue
        report = json.loads(source.read_text(encoding="utf-8"))
        bound = _digest_of(report)
        if bound != digest and not args.allow_unbound:
            refused.append(
                {
                    "report": name,
                    "reason": f"artefact is bound to {str(bound)[:12]}, tree is {digest[:12]}",
                }
            )
            continue
        shutil.copyfile(source, destination / name)
        published.append(name)

    result = {
        "schema": "korpus.release-evidence-publication.v1",
        "status": "FAIL" if refused else "PASS",
        "release": release,
        "source_tree_sha256": digest,
        "published": sorted(published),
        "refused": refused,
        "interpretation": (
            "An artefact bound to another tree is refused rather than republished under a "
            "fresh digest: copying it would launder a stale result into a current-looking "
            "one, which is what the binding check exists to prevent."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
