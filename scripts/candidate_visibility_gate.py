"""Fail-closed validation of candidate-visibility mutation evidence."""
from __future__ import annotations

import json
from pathlib import Path

from korpus.application.provenance import read_provenance


def _read_report(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def candidate_visibility_evidence(path: Path, source_digest: str) -> tuple[dict[str, bool], dict]:
    report = _read_report(path)
    try:
        provenance = read_provenance(report) if report else None
        source_bound = provenance is not None and provenance.source_digest == source_digest
    except (TypeError, ValueError):
        source_bound = False
    total = int(report.get("mutants", 0) or 0)
    executed = int(report.get("executed_mutants", 0) or 0)
    killed = int(report.get("killed", 0) or 0)
    survived = report.get("survived") or []
    invalid = report.get("invalid") or []
    complete = bool(report) and total > 0
    checks = {
        "candidate_visibility_report_present": bool(report),
        "candidate_visibility_source_bound": source_bound,
        "candidate_visibility_catalogue_nonempty": total > 0,
        "candidate_visibility_all_executed": complete and executed == total,
        "candidate_visibility_all_killed": (
            complete and killed == total and not survived and not invalid
        ),
        "candidate_visibility_report_pass": report.get("status") == "PASS",
    }
    evidence = {
        "schema": report.get("schema"),
        "mutants": total,
        "executed_mutants": executed,
        "killed": killed,
        "survived": survived,
        "invalid": invalid,
    }
    return checks, evidence
