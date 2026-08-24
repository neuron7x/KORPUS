#!/usr/bin/env python3
"""Aggregate exact local release evidence without impersonating production authorization.

Every accepted local report must belong to the current release and source digest.  This
prevents a stale green report from authorizing a changed tree.  External/production-like
controls remain explicit blockers; absence can never be converted into PASS locally.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Callable
from pathlib import Path

from korpus.application.provenance import compute_source_digest
from korpus.application.release_numeric import preflight_report_pass

release_tag = __import__(
    "scripts.release_identity" if __package__ else "release_identity", fromlist=["release_tag"]
).release_tag

ROOT = Path(__file__).resolve().parents[1]


def assurance_policy(root: Path) -> dict[str, object]:
    return json.loads((root / "config/operations/reference-v5.json").read_text(encoding="utf-8"))[
        "assurance"
    ]


REPORT_NAMES = {
    "backend": "FULL_BACKEND_REPORT.json",
    "coverage": "COVERAGE_REPORT.json",
    "coverage_ratchet": "COVERAGE_GAP_PLAN.json",
    "determinism": "DETERMINISM_GATE.json",
    "stress": "STRESS_GATE.json",
    "plasticity": "PLASTICITY_GATE.json",
    "dependency_locks": "DEPENDENCY_LOCK_REPORT.json",
    "builtin_security": "BUILTIN_SECURITY_GATE.json",
    "inference_security": "INFERENCE_SECURITY_GATE.json",
    "standards_map": "STANDARDS_CONTROL_MAP_VERIFICATION.json",
    "mutation_delta": "MUTATION_DELTA_REPORT.json",
}
EXTERNAL_TOOLS = {
    "ruff": "QUALITY_RUFF_UNAVAILABLE",
    "mypy": "QUALITY_MYPY_UNAVAILABLE",
    "pip-audit": "PYTHON_VULNERABILITY_SCANNER_UNAVAILABLE",
    "osv-scanner": "OSV_SCANNER_UNAVAILABLE",
    "gitleaks": "SECRET_SCANNER_UNAVAILABLE",
    "trivy": "CONTAINER_OS_SCANNER_UNAVAILABLE",
    "docker": "REAL_POSTGRES_CONTAINER_RUNTIME_UNAVAILABLE",
    "psql": "POSTGRES_CLIENT_UNAVAILABLE",
    "cosign": "TRUSTED_ARTIFACT_SIGNING_TOOL_UNAVAILABLE",
}
INHERENT_EXTERNAL = (
    "EXTERNAL_INDEPENDENT_REDTEAM_REQUIRED",
    "REAL_POSTGRES_PRODUCTION_LIKE_EVIDENCE_REQUIRED",
    "TRUSTED_HOSTED_BUILDER_ATTESTATION_REQUIRED",
    "EXACT_DEPLOYMENT_ENVIRONMENT_ATTESTATION_REQUIRED",
)


def release_report_dir(root: Path) -> Path:
    return root / "reports" / "release" / release_tag(root)


def _load(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _report_pass(name: str, report: dict[str, object], policy: dict[str, object]) -> bool:
    return preflight_report_pass(name, report, policy)


def _bound_to_current(report: dict[str, object], source_digest: str, release: str) -> bool:
    return report.get("source_tree_sha256") == source_digest and report.get("release") == release


def evaluate(root: Path, which: Callable[[str], str | None] = shutil.which) -> dict[str, object]:
    source_digest = compute_source_digest(root)
    release = release_tag(root)
    policy = assurance_policy(root)
    report_dir = release_report_dir(root)
    local_checks: dict[str, bool] = {}
    report_meta: dict[str, object] = {}
    for name, filename in REPORT_NAMES.items():
        path = report_dir / filename
        report = _load(path)
        semantic_pass = bool(report) and _report_pass(name, report, policy)
        source_bound = bool(report) and _bound_to_current(report, source_digest, release)
        local_checks[name] = semantic_pass and source_bound
        report_meta[name] = {
            "path": path.relative_to(root).as_posix(),
            "status": report.get("status"),
            "release": report.get("release"),
            "source_tree_sha256": report.get("source_tree_sha256"),
            "source_bound": source_bound,
        }
    unavailable = [blocker for tool, blocker in EXTERNAL_TOOLS.items() if which(tool) is None]
    blockers = sorted({*INHERENT_EXTERNAL, *unavailable})
    local_pass = all(local_checks.values())
    return {
        "schema": "korpus.local-production-preflight.v2",
        "status": "PASS_WITH_EXTERNAL_BLOCKERS" if local_pass else "FAIL_LOCAL",
        "release": release,
        "source_tree_sha256": source_digest,
        "local_checks": local_checks,
        "reports": report_meta,
        "external_blockers": blockers,
        "production_authorized": False,
        "authorization_reason": (
            "formal production authorization requires independent, production-like and "
            "trusted-builder evidence that cannot be self-attested by this local build"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    report = evaluate(root)
    out = args.out or (release_report_dir(root) / "LOCAL_PRODUCTION_PREFLIGHT.json")
    out = out if out.is_absolute() else root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS_WITH_EXTERNAL_BLOCKERS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
