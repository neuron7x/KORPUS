#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from source_digest import source_tree_digest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.assurance import evaluate_assurance  # noqa: E402  (path set above)
from korpus.application.provenance import compute_source_digest  # noqa: E402

VAR = ROOT / "var"
POLICY = ROOT / "config/operations/reference-v5.json"
REPORTS = {
    "eval": VAR / "eval-report.json",
    "mutation": VAR / "mutation-report.json",
    "migration": VAR / "migration-report.json",
    "scale": VAR / "scale-report.json",
    "operational": VAR / "operational-gate.json",
}
# Produced by api:postgres-and-restore, which needs docker. Not in `required`: its
# absence has to reach the verdict as a failed predicate that names what is missing,
# not as a crash listing a path. The verdict is FAIL either way — that is the point.
OPTIONAL_REPORTS = {"recovery": VAR / "recovery-report.json"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    required = [
        *REPORTS.values(),
        VAR / "pytest.xml",
        VAR / "coverage.xml",
        VAR / "quality-report.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print(json.dumps({"status": "FAIL", "missing": missing}, indent=2))
        return 1
    loaded = {name: json.loads(path.read_text()) for name, path in REPORTS.items()}
    loaded.update(
        {
            name: json.loads(path.read_text())
            for name, path in OPTIONAL_REPORTS.items()
            if path.is_file()
        }
    )
    quality = json.loads((VAR / "quality-report.json").read_text())
    junit_root = ET.parse(VAR / "pytest.xml").getroot()
    suite = junit_root if junit_root.tag == "testsuite" else junit_root.find("testsuite")
    if suite is None:
        raise SystemExit("invalid JUnit report")
    coverage = ET.parse(VAR / "coverage.xml").getroot()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    result = evaluate_assurance(
        policy,
        suite.attrib,
        coverage.attrib,
        loaded,
        quality,
        compute_source_digest(ROOT),
    )
    checks = dict(result.checks)
    report = {
        "schema_version": 5,
        "status": result.status,
        "failures": list(result.failures),
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
        "evidence_sha256": {
            name: digest(path)
            for name, path in (*REPORTS.items(), *OPTIONAL_REPORTS.items())
            if path.is_file()
        },
        # Recorded executions, not a declaration of intent: an unexecuted tool now
        # keeps the aggregate verdict red (quality_tooling_executed).
        "quality_tooling": {
            name: {key: value for key, value in tool.items() if key != "output_tail"}
            for name, tool in quality.get("tools", {}).items()
        },
        "limitations": [
            (
                "PostgreSQL/pgvector, backup-restore, and container execution remain "
                "GitLab gates; one local test is skipped."
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
