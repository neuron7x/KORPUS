#!/usr/bin/env python3
"""Publish only source-bound release evidence from exactly validated bytes.

Reject missing, ambiguous or stale reports. Never re-read a candidate after checking
its source binding. Coverage remains blocked until issue #66 supplies authenticated
GitHub run/attempt/artifact-byte admission.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.final_release_evidence import strict_signed_json_object  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from korpus.application.release_claims import binding  # noqa: E402
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
    "WEB_REGRESSION_REPORT.json": "var/web-regression.json",
}


def coverage_projection(digest: str, release: str) -> dict[str, Any] | None:
    """Fail closed until GitHub-imported coverage is verified against exact artifact bytes.

    Raw local coverage JSON is not proof of execution or GitHub run identity.
    Issue #66 must supply a verified importer/admission path before publication.
    """
    return None


def _admit_reports(digest: str, refused: list[dict[str, str]]) -> list[tuple[str, bytes]]:
    approved: list[tuple[str, bytes]] = []
    for name, relative in SOURCES.items():
        source = ROOT / relative
        if not source.is_file():
            refused.append({"report": name, "reason": f"no artefact at {relative}"})
            continue
        try:
            payload = source.read_bytes()
            report = dict(strict_signed_json_object(payload, f"release report {name}"))
        except (OSError, ValueError) as error:
            refused.append({"report": name, "reason": f"invalid source evidence: {error}"})
            continue
        bound, divergent = binding(report)
        if divergent:
            refused.append({"report": name, "reason": "дві прив'язки в артефакті розійшлись"})
            continue
        if bound != digest:
            refused.append(
                {
                    "report": name,
                    "reason": f"artefact is bound to {str(bound)[:12]}, tree is {digest[:12]}",
                }
            )
            continue
        approved.append((name, payload))
    return approved


def main() -> int:
    argparse.ArgumentParser().parse_args()

    release = release_tag(ROOT)
    digest = compute_source_digest(ROOT)
    destination = ROOT / "reports/release" / release
    destination.mkdir(parents=True, exist_ok=True)

    # Revoke stale output before verifying this attempt.
    for name in ("COVERAGE_REPORT.json", *SOURCES):
        (destination / name).unlink(missing_ok=True)

    published: list[str] = []
    refused: list[dict[str, str]] = []

    coverage = coverage_projection(digest, release)
    if coverage is None:
        refused.append({"report": "COVERAGE_REPORT.json", "reason": "no coverage totals on disk"})

    approved = _admit_reports(digest, refused)

    # Never leave a partial PASS-looking release after any evidence refusal.
    if not refused:
        assert coverage is not None
        (destination / "COVERAGE_REPORT.json").write_text(
            json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        published.append("COVERAGE_REPORT.json")
        for name, payload in approved:
            (destination / name).write_bytes(payload)
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
