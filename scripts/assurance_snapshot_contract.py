"""The producer and both consumers share one canonical research snapshot contract."""

from __future__ import annotations

import hashlib
from pathlib import Path

from path_admission import regular_file

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


def limitations_valid(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _record_valid(record: object) -> bool:
    return (
        isinstance(record, dict)
        and set(record) == {"path", "bytes", "sha256"}
        and isinstance(record.get("path"), str)
        and type(record.get("bytes")) is int
        and isinstance(record.get("sha256"), str)
    )


def snapshot_contract_valid(snapshot: object) -> bool:
    if not isinstance(snapshot, dict):
        return False
    records = snapshot.get("records")
    return (
        set(snapshot) == {"schema", "release", "status", "records", "limitations"}
        and snapshot.get("schema") == "korpus.assurance-snapshot.v1"
        and limitations_valid(snapshot.get("limitations"))
        and isinstance(records, list)
        and all(_record_valid(record) for record in records)
    )


def complete_snapshot_records(root: Path, value: object) -> list[dict[str, object]]:
    records = value if isinstance(value, list) else []
    if not all(_record_valid(record) for record in records):
        return []
    expected = {f"reports/{name}" for name in (*SOURCES, "RESEARCH_ASSURANCE_REPORT.json")}
    paths = {str(item["path"]) for item in records}
    if len(paths) != len(records) or paths != expected:
        return []
    valid = all(
        regular_file(path := root / str(item["path"]))
        and path.stat().st_size == item.get("bytes")
        and hashlib.sha256(path.read_bytes()).hexdigest() == item.get("sha256")
        for item in records
    )
    return records if valid else []
