#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from source_digest import source_tree_digest

ROOT = Path(__file__).resolve().parents[1]
VAR = ROOT / "var"
REPORTS = {
    "eval": VAR / "eval-report.json",
    "mutation": VAR / "mutation-report.json",
    "migration": VAR / "migration-report.json",
    "scale": VAR / "scale-report.json",
    "operational": VAR / "operational-gate.json",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    required = [*REPORTS.values(), VAR / "pytest.xml", VAR / "coverage.xml"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print(json.dumps({"status": "FAIL", "missing": missing}, indent=2))
        return 1
    loaded = {name: json.loads(path.read_text()) for name, path in REPORTS.items()}
    junit_root = ET.parse(VAR / "pytest.xml").getroot()
    suite = junit_root if junit_root.tag == "testsuite" else junit_root.find("testsuite")
    if suite is None:
        raise SystemExit("invalid JUnit report")
    coverage = ET.parse(VAR / "coverage.xml").getroot()
    checks = {
        "pytest": suite.attrib.get("failures") == "0" and suite.attrib.get("errors") == "0",
        "coverage_line": float(coverage.attrib.get("line-rate", 0)) >= 0.82,
        "eval": loaded["eval"].get("pass_rate") == 1.0,
        # Over the whole catalogue, not over the mutants that still apply. A mutant
        # whose target line was reformatted goes INVALID and drops out of
        # mutation_score's denominator, which then reads 1.000 for a catalogue that
        # shrank — observed 2026-08-03 with four security mutants. See ADR-0008.
        "mutation": loaded["mutation"].get("mutation_score_over_catalogue") == 1.0,
        "migration": loaded["migration"].get("table_set_match") is True,
        "scale": loaded["scale"].get("status") == "PASS",
        "operational": loaded["operational"].get("status") == "PASS",
    }
    report = {
        "schema_version": 4,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "provenance": "ASSEMBLED_FROM_INDIVIDUALLY_EXECUTED_LOCAL_GATES",
        "source_tree_sha256": source_tree_digest(),
        "checks": checks,
        "pytest": {
            key: suite.attrib.get(key, "0")
            for key in ("tests", "failures", "errors", "skipped", "time")
        },
        "coverage": {
            "line_rate": float(coverage.attrib.get("line-rate", 0)),
            "branch_rate": float(coverage.attrib.get("branch-rate", 0)),
        },
        **loaded,
        "evidence_sha256": {name: digest(path) for name, path in REPORTS.items()},
        "quality_tooling": {
            "ruff": "NOT_EXECUTED_LOCAL_PACKAGE_UNAVAILABLE; REQUIRED_IN_GITLAB",
            "mypy": "NOT_EXECUTED_LOCAL_PACKAGE_UNAVAILABLE; REQUIRED_IN_GITLAB",
        },
        "limitations": [
            (
                "PostgreSQL/pgvector, backup-restore, and container execution remain "
                "GitLab gates; one local test is skipped."
            ),
            (
                "Ruff and mypy packages were unavailable in this runtime and remain "
                "mandatory GitLab jobs."
            ),
            "Synthetic local scale evidence is not a production SLA.",
            "Passing software gates is not corpus, cyber, regulatory or military authorization.",
        ],
    }
    output = VAR / "research-assurance-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    summary = {
        "status": report["status"],
        "checks": checks,
        "source_tree_sha256": report["source_tree_sha256"],
    }
    print(json.dumps(summary, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
