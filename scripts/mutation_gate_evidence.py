"""Source-bound evidence loader for the production mutation gate."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from korpus.application.provenance import read_provenance


@dataclass(frozen=True, slots=True)
class MutationGateEvidence:
    checks: dict[str, bool]
    total: int
    valid: int
    killed: int
    snapshot_total: int
    snapshot_killed: int


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _source_bound(report: dict, source: str) -> bool:
    try:
        provenance = read_provenance(report) if report else None
        return provenance is not None and provenance.source_digest == source
    except (TypeError, ValueError):
        return False


def load_mutation_gate_evidence(
    report_path: Path,
    snapshot_path: Path,
    source: str,
) -> MutationGateEvidence:
    report = _read(report_path)
    snapshot = _read(snapshot_path)
    total = int(report.get("mutants", 0) or 0)
    valid = int(report.get("valid_mutants", 0) or 0)
    killed = int(report.get("killed", 0) or 0)
    snapshot_total = int(snapshot.get("mutants", 0) or 0)
    snapshot_executed = int(snapshot.get("executed_mutants", 0) or 0)
    snapshot_killed = int(snapshot.get("killed", 0) or 0)
    checks = {
        "report_present": bool(report),
        "source_bound": _source_bound(report, source),
        "catalogue_nonempty": total > 0,
        "all_mutants_valid": valid == total and not report.get("invalid"),
        "all_valid_mutants_killed": killed == valid and not report.get("survived"),
        "catalogue_score_one": report.get("mutation_score_over_catalogue") == 1.0,
        "snapshot_report_present": bool(snapshot),
        "snapshot_source_bound": _source_bound(snapshot, source),
        "snapshot_catalogue_nonempty": snapshot_total > 0,
        "snapshot_all_mutants_executed": snapshot_executed == snapshot_total,
        "snapshot_all_mutants_killed": (
            snapshot.get("status") == "PASS"
            and snapshot_killed == snapshot_total
            and not snapshot.get("survived")
            and not snapshot.get("invalid")
        ),
    }
    return MutationGateEvidence(
        checks, total, valid, killed, snapshot_total, snapshot_killed
    )
