#!/usr/bin/env python3
"""Promote successful assurance outputs into content-hashed release evidence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_identity import release_tag

ROOT = Path(__file__).resolve().parents[1]
VAR = ROOT / "var"
REPORTS = ROOT / "reports"
SOURCES = {
    "PYTEST_REPORT.xml": "pytest.xml",
    "COVERAGE_REPORT.xml": "coverage.xml",
    "COVERAGE_REPORT.json": "coverage.json",
    "EVAL_REPORT.json": "eval-report.json",
    "MUTATION_REPORT.json": "mutation-report.json",
    "MIGRATION_REPORT.json": "migration-report.json",
    "SCALE_REPORT.json": "scale-report.json",
    "OPERATIONAL_GATE.json": "operational-gate.json",
    "SUPPLY_CHAIN_INVENTORY.json": "supply-chain-inventory.json",
    "INFRASTRUCTURE_VALIDATION.json": "infrastructure-validation.json",
    "KUBERNETES_VALIDATION.json": "kubernetes-validation.json",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise SystemExit(f"missing assurance output: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"assurance output is not an object: {path}")
    return value


def assemble_ci_report() -> dict[str, object]:
    junit = VAR / "pytest.xml"
    coverage = VAR / "coverage.xml"
    if not junit.is_file() or not coverage.is_file():
        raise SystemExit("missing aggregate report and CI pytest/coverage artifacts")
    junit_root = ET.parse(junit).getroot()
    suite = junit_root if junit_root.tag == "testsuite" else junit_root.find("testsuite")
    if suite is None:
        raise SystemExit("invalid JUnit report")
    coverage_root = ET.parse(coverage).getroot()
    eval_report = load_json(VAR / "eval-report.json")
    mutation_report = load_json(VAR / "mutation-report.json")
    migration_report = load_json(VAR / "migration-report.json")
    scale_report = load_json(VAR / "scale-report.json")
    operational_report = load_json(VAR / "operational-gate.json")
    hard_pass = (
        suite.attrib.get("failures", "0") == "0"
        and suite.attrib.get("errors", "0") == "0"
        and eval_report.get("status_accuracy") == 1.0
        and eval_report.get("leakage_failures") == 0
        # Over the whole catalogue: an INVALID mutant leaves mutation_score's
        # denominator and would otherwise keep the figure at 1.000 (ADR-0008).
        and mutation_report.get("mutation_score_over_catalogue") == 1.0
        and migration_report.get("table_set_match") is True
        and migration_report.get("sqlite_fts5_present") is True
        and scale_report.get("status") == "PASS"
        and operational_report.get("status") == "PASS"
    )
    return {
        "schema_version": 2,
        "status": "PASS" if hard_pass else "FAIL",
        "provenance": "CI_ARTIFACT_ASSEMBLY",
        "pipeline": {
            "id": os.getenv("CI_PIPELINE_ID", "UNKNOWN"),
            "commit_sha": os.getenv("CI_COMMIT_SHA", "UNKNOWN"),
            "job_id": os.getenv("CI_JOB_ID", "UNKNOWN"),
        },
        "pytest": {
            key: suite.attrib.get(key, "0")
            for key in ("tests", "failures", "errors", "skipped", "time")
        },
        "coverage": {
            "line_rate": float(coverage_root.attrib.get("line-rate", "0")),
            "branch_rate": float(coverage_root.attrib.get("branch-rate", "0")),
        },
        "eval": eval_report,
        "mutation": mutation_report,
        "migration": migration_report,
        "scale": scale_report,
        "operational": operational_report,
        "limitations": [
            (
                "The package job runs only after required CI gates succeed; "
                "their logs remain CI artifacts."
            ),
            "Synthetic evaluation does not authorize real restricted corpus deployment.",
        ],
    }


#: The var artifacts the operational gate hashed, keyed by the name it stored the digest
#: under in `evidence_sha256`. Promotion re-hashes each and refuses on any mismatch: the
#: gate can only have passed over the bytes it hashed, and promoting a different file
#: beside that PASS is the exact "green next to a stale artifact" this project exists to
#: refuse. Not a paranoia check — it caught a FAIL operational-gate.json sitting in var
#: while a PASS assurance was assembled from CI artifacts (2026-08-08).
_GATE_HASHED_EVIDENCE = {
    "eval": "eval-report.json",
    "mutation": "mutation-report.json",
    "migration": "migration-report.json",
    "scale": "scale-report.json",
}


def _verify_evidence_matches_the_gate() -> None:
    gate = VAR / "operational-gate.json"
    if not gate.is_file():
        # No gate ran — assemble_ci_report already refuses a non-PASS assurance, and a
        # missing gate is a non-PASS. Nothing to cross-check here.
        return
    recorded = load_json(gate).get("evidence_sha256")
    if not isinstance(recorded, dict):
        raise SystemExit(
            "operational gate carries no evidence_sha256; it predates the promotion "
            "cross-check and cannot be trusted to describe the artifacts being promoted"
        )
    for name, filename in _GATE_HASHED_EVIDENCE.items():
        expected = recorded.get(name)
        source = VAR / filename
        if expected is None or not source.is_file():
            raise SystemExit(f"operational gate did not hash {name}; refusing to promote")
        actual = sha256(source)
        if actual != expected:
            raise SystemExit(
                f"{filename} does not match the digest the operational gate hashed "
                f"({actual[:12]}… != {expected[:12]}…): the gate passed over a different "
                "file than the one about to be promoted. Re-run the gate on this evidence."
            )


def main() -> int:
    assurance_path = VAR / "research-assurance-report.json"
    assurance = load_json(assurance_path) if assurance_path.is_file() else assemble_ci_report()
    if assurance.get("status") != "PASS":
        raise SystemExit("refusing to snapshot a failing assurance run")
    _verify_evidence_matches_the_gate()

    REPORTS.mkdir(exist_ok=True)
    assurance_path = REPORTS / "RESEARCH_ASSURANCE_REPORT.json"
    assurance_path.write_text(
        json.dumps(assurance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    records: list[dict[str, object]] = [
        {
            "path": assurance_path.relative_to(ROOT).as_posix(),
            "bytes": assurance_path.stat().st_size,
            "sha256": sha256(assurance_path),
        }
    ]
    for destination_name, source_name in SOURCES.items():
        source = VAR / source_name
        if not source.is_file():
            raise SystemExit(f"missing assurance output: {source}")
        destination = REPORTS / destination_name
        shutil.copyfile(source, destination)
        records.append(
            {
                "path": destination.relative_to(ROOT).as_posix(),
                "bytes": destination.stat().st_size,
                "sha256": sha256(destination),
            }
        )

    index = {
        "schema": "korpus.assurance-snapshot.v1",
        "release": os.getenv("KORPUS_RELEASE_VERSION", release_tag()),
        "status": "PASS",
        "records": records,
        "limitations": assurance.get("limitations", []),
    }
    index_path = REPORTS / "ASSURANCE_SNAPSHOT.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(index, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
