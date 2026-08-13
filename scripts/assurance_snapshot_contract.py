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


def canonical_snapshot_records(
    snapshot: object,
) -> tuple[tuple[str, ...], tuple[dict[str, object], ...]]:
    """Validate structure and return records in canonical order only on success."""
    if not isinstance(snapshot, dict):
        return ("assurance snapshot is not an object",), ()

    failures: list[str] = []
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        failures.append("assurance snapshot schema mismatch")
    raw_records = snapshot.get("records")
    if not isinstance(raw_records, list):
        return (*failures, "assurance snapshot records are missing or malformed"), ()

    records: list[dict[str, object]] = []
    paths: list[str] = []
    for record in raw_records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            failures.append("assurance snapshot contains malformed record")
            continue
        records.append(record)
        paths.append(str(record["path"]))

    duplicates = sorted({path for path in paths if paths.count(path) > 1})
    expected = set(canonical_snapshot_paths())
    actual = set(paths)
    if duplicates:
        failures.append(f"assurance snapshot duplicate records: {duplicates}")
    if missing := sorted(expected - actual):
        failures.append(f"assurance snapshot missing canonical records: {missing}")
    if extra := sorted(actual - expected):
        failures.append(f"assurance snapshot contains non-canonical records: {extra}")
    if failures:
        return tuple(failures), ()

    by_path = {str(record["path"]): record for record in records}
    return (), tuple(by_path[path] for path in canonical_snapshot_paths())
