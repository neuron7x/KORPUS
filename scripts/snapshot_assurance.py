#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "apps/api/src")]
from assurance_publication import publish  # noqa: E402
from evidence_source_binding import evidence_source_binding_failure  # noqa: E402
from korpus.application.final_release_evidence import strict_signed_json_object  # noqa: E402
from path_admission import regular_file, symlink_free  # noqa: E402
from release_identity import release_tag  # noqa: E402
from source_digest import source_tree_digest  # noqa: E402

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
    if not regular_file(path):
        raise SystemExit(f"missing or symlinked assurance output: {path}")
    return dict(strict_signed_json_object(path.read_bytes(), f"assurance output {path}"))


def limitations_valid(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def snapshot_contract_valid(snapshot: object) -> bool:
    if not isinstance(snapshot, dict):
        return False
    records = snapshot.get("records")
    return (
        set(snapshot) == {"schema", "release", "status", "records", "limitations"}
        and snapshot.get("schema") == "korpus.assurance-snapshot.v1"
        and limitations_valid(snapshot.get("limitations"))
        and isinstance(records, list)
        and all(
            isinstance(record, dict)
            and set(record) == {"path", "bytes", "sha256"}
            and isinstance(record.get("path"), str)
            and type(record.get("bytes")) is int
            and isinstance(record.get("sha256"), str)
            for record in records
        )
    )


def complete_snapshot_records(value: object) -> list[dict[str, object]]:
    records = value if isinstance(value, list) else []
    expected = {f"reports/{name}" for name in (*SOURCES, "RESEARCH_ASSURANCE_REPORT.json")}
    paths = {str(item.get("path", "")) for item in records if isinstance(item, dict)}
    if len(paths) != len(records) or paths != expected:
        return []
    valid = all(
        regular_file(path := ROOT / str(item["path"]))
        and path.stat().st_size == item.get("bytes")
        and hashlib.sha256(path.read_bytes()).hexdigest() == item.get("sha256")
        for item in records
    )
    return records if valid else []


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
        "limitations": ["Package gate logs stay in CI.", "Restricted deployment is unauthorized."],
    }


_GATE_HASHED_EVIDENCE = {
    "eval": "eval-report.json",
    "mutation": "mutation-report.json",
    "migration": "migration-report.json",
    "scale": "scale-report.json",
}


def _verify_evidence_matches_the_gate() -> None:
    gate = VAR / "operational-gate.json"
    if not gate.is_file():
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


def _verify_evidence_source_is_committed(assurance: dict[str, object]) -> None:
    scope = assurance.get("digest_scope")
    claimed = assurance.get("evidence_source_sha256")
    if claimed is None:
        provenance = assurance.get("provenance")
        if isinstance(provenance, dict):
            claimed = provenance.get("source_digest")
            scope = scope or provenance.get("digest_scope") or "evidence_paths"
    if claimed is None:
        raise SystemExit(
            "assurance report names no evidence source digest: promoting it would "
            "publish evidence that cannot be bound to any commit"
        )
    if scope == "tracked_tree":
        expected = source_tree_digest("HEAD")
        failure = (
            None
            if isinstance(claimed, str) and claimed.lower() == expected
            else "assurance evidence source digest does not match committed HEAD"
        )
    elif scope == "evidence_paths":
        failure = evidence_source_binding_failure(claimed, root=ROOT)
    else:
        raise SystemExit(f"assurance report declares an unknown digest scope {scope!r}")
    if failure is not None:
        raise SystemExit(
            f"{failure}: доказ описує стан, якого немає в жодному коміті, "
            "тож відтворити його пізніше неможливо"
        )


def main() -> int:
    assurance_path = VAR / "research-assurance-report.json"
    assurance = load_json(assurance_path) if assurance_path.is_file() else assemble_ci_report()
    if assurance.get("status") != "PASS":
        raise SystemExit("refusing to snapshot a failing assurance run")
    limitations = assurance.get("limitations", [])
    if not limitations_valid(limitations):
        raise SystemExit("assurance limitations must be a list of strings")
    _verify_evidence_matches_the_gate()
    _verify_evidence_source_is_committed(assurance)

    if not symlink_free(REPORTS):
        raise SystemExit("assurance reports directory must not be a symlink")
    REPORTS.mkdir(exist_ok=True)
    assurance_path = REPORTS / "RESEARCH_ASSURANCE_REPORT.json"
    publish(assurance_path, (json.dumps(assurance, ensure_ascii=False, indent=2) + "\n").encode())
    records: list[dict[str, object]] = [
        {
            "path": assurance_path.relative_to(ROOT).as_posix(),
            "bytes": assurance_path.stat().st_size,
            "sha256": sha256(assurance_path),
        }
    ]
    for destination_name, source_name in SOURCES.items():
        source = VAR / source_name
        if not regular_file(source):
            raise SystemExit(f"missing assurance output: {source}")
        destination = REPORTS / destination_name
        publish(destination, source.read_bytes())
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
        "limitations": limitations,
    }
    index_path = REPORTS / "ASSURANCE_SNAPSHOT.json"
    publish(index_path, (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps(index, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
