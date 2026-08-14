from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from candidate_visibility_gate import candidate_visibility_evidence  # noqa: E402


def _report(source_digest: str, *, killed: int = 3, status: str = "PASS") -> dict:
    return {
        "schema": "korpus.candidate-visibility-mutation.v1",
        "provenance": {
            "schema_version": 1,
            "source_digest": source_digest,
            "generator": "scripts/run_candidate_visibility_mutation_tests.py",
            "generated_at": "2026-08-14T00:00:00+00:00",
        },
        "mutants": 3,
        "executed_mutants": 3,
        "killed": killed,
        "survived": [] if killed == 3 else ["CV03"],
        "invalid": [],
        "status": status,
    }


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_candidate_mutation_evidence_accepts_only_complete_source_bound_kills(tmp_path) -> None:
    source = "a" * 64
    path = tmp_path / "candidate.json"
    _write(path, _report(source))

    checks, evidence = candidate_visibility_evidence(path, source)

    assert all(checks.values())
    assert evidence["mutants"] == evidence["executed_mutants"] == evidence["killed"] == 3


def test_candidate_mutation_evidence_rejects_stale_source(tmp_path) -> None:
    path = tmp_path / "candidate.json"
    _write(path, _report("a" * 64))

    checks, _ = candidate_visibility_evidence(path, "b" * 64)

    assert checks["candidate_visibility_source_bound"] is False


def test_candidate_mutation_evidence_rejects_any_survivor(tmp_path) -> None:
    source = "a" * 64
    path = tmp_path / "candidate.json"
    _write(path, _report(source, killed=2, status="FAIL"))

    checks, evidence = candidate_visibility_evidence(path, source)

    assert checks["candidate_visibility_all_killed"] is False
    assert checks["candidate_visibility_report_pass"] is False
    assert evidence["survived"] == ["CV03"]
