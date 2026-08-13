"""Canonical structure of promoted research-assurance snapshots."""
from __future__ import annotations

SNAPSHOT_SCHEMA = "korpus.assurance-snapshot.v1"
RESEARCH_REPORT_PATH = "reports/RESEARCH_ASSURANCE_REPORT.json"
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


def canonical_snapshot_paths() -> tuple[str, ...]:
    return (RESEARCH_REPORT_PATH, *(f"reports/{name}" for name in SOURCES))


def _record_index(
    records: list[object],
) -> tuple[tuple[str, ...], dict[str, dict[str, object]]]:
    failures: list[str] = []
    by_path: dict[str, dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            failures.append("assurance snapshot contains malformed record")
            continue
        path = str(record["path"])
        if path in by_path:
            failures.append(f"assurance snapshot duplicate record: {path}")
            continue
        by_path[path] = record
    return tuple(failures), by_path


def canonical_snapshot_records(
    snapshot: object, expected_release: str
) -> tuple[tuple[str, ...], tuple[dict[str, object], ...]]:
    """Return canonical records only when the complete snapshot contract is valid."""
    if not isinstance(snapshot, dict):
        return ("assurance snapshot is not an object",), ()

    failures: list[str] = []
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        failures.append("assurance snapshot schema mismatch")
    if snapshot.get("status") != "PASS" or snapshot.get("release") != expected_release:
        failures.append("assurance snapshot release/status mismatch")
    raw_records = snapshot.get("records")
    if not isinstance(raw_records, list):
        return (*failures, "assurance snapshot records are missing or malformed"), ()

    record_failures, by_path = _record_index(raw_records)
    failures.extend(record_failures)
    expected = set(canonical_snapshot_paths())
    actual = set(by_path)
    if missing := sorted(expected - actual):
        failures.append(f"assurance snapshot missing canonical records: {missing}")
    if extra := sorted(actual - expected):
        failures.append(f"assurance snapshot contains non-canonical records: {extra}")
    if failures:
        return tuple(failures), ()
    return (), tuple(by_path[path] for path in canonical_snapshot_paths())
