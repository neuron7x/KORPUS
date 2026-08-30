#!/usr/bin/env python3
"""Sandboxed first-order mutation campaign for release-critical invariants."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT)]

from korpus.application.provenance import compute_source_digest  # noqa: E402

from scripts.release_identity import release_tag  # noqa: E402


@dataclass(frozen=True)
class Mutant:
    mutant_id: str
    path: str
    old: str
    new: str
    tests: tuple[str, ...]
    invariant: str


MUTANTS = (
    Mutant(
        "A01_PASS_DOMINATES_FAIL",
        "apps/api/src/korpus/application/assurance_calculus.py",
        'outcome_dominates = right.status == "UNKNOWN" or left.status == right.status',
        'outcome_dominates = right.status == "UNKNOWN" or left.status == right.status or left.status == "PASS"',
        ("apps/api/tests/test_assurance_calculus.py",),
        "PASS and FAIL are incomparable evidence outcomes",
    ),
    Mutant(
        "A02_CONFLICT_JOIN_UPGRADES_TO_PASS",
        "apps/api/src/korpus/application/assurance_calculus.py",
        '        status = "FAIL"\n    return EvidencePoint(',
        '        status = "PASS"\n    return EvidencePoint(',
        (
            "apps/api/tests/test_assurance_calculus.py",
            "apps/api/tests/test_assurance_model_check.py",
        ),
        "contradictory PASS/FAIL evidence joins fail-closed",
    ),
    Mutant(
        "R01_GENERIC_WITHDRAWAL_BYPASS",
        "apps/api/src/korpus/application/release_state_machine.py",
        "    if target == ReleaseStage.WITHDRAWN:\n",
        "    if False and target == ReleaseStage.WITHDRAWN:\n",
        ("apps/api/tests/test_release_state_machine.py",),
        "withdrawal requires the reason-bearing withdrawal API",
    ),
    Mutant(
        "L01_LEDGER_EVENT_HASH_BYPASS",
        "apps/api/src/korpus/application/release_ledger.py",
        "    if event.event_sha256 != event.computed_sha256:\n",
        "    if False and event.event_sha256 != event.computed_sha256:\n",
        ("apps/api/tests/test_release_ledger.py",),
        "release-ledger event bytes are hash-bound",
    ),
    Mutant(
        "L02_LEDGER_PREVIOUS_HASH_BYPASS",
        "apps/api/src/korpus/application/release_ledger.py",
        "    if event.previous_event_sha256 != previous_hash:\n",
        "    if False and event.previous_event_sha256 != previous_hash:\n",
        ("apps/api/tests/test_release_ledger.py",),
        "release-ledger event ordering is chained",
    ),
    Mutant(
        "D01_DIRECT_URL_DEPENDENCY_ACCEPTED",
        "scripts/verify_dependency_locks.py",
        '    if raw.startswith(_UNSAFE_PREFIXES) or " @ " in raw or ";" in raw:\n',
        '    if raw.startswith(_UNSAFE_PREFIXES) or ";" in raw:\n',
        ("apps/api/tests/test_dependency_lock_gate.py",),
        "dependency locks reject non-hermetic direct URLs",
    ),
    Mutant(
        "S01_ARTIFACT_DIGEST_IGNORED",
        "scripts/slsa_provenance.py",
        '    if not isinstance(digest, dict) or digest.get("sha256") != sha256(artifact):\n',
        "    if not isinstance(digest, dict) or False:\n",
        ("apps/api/tests/test_slsa_provenance.py",),
        "provenance subject binds the completed artifact digest",
    ),
    Mutant(
        "I01_RETRIEVAL_CONTROL_INJECTION_ALLOWED",
        "apps/api/src/korpus/application/evidence.py",
        '    blocked = (override and target) or "role_marker" in reasons or score >= 3\n',
        "    blocked = False\n",
        (
            "apps/api/tests/test_indirect_prompt_injection_boundary.py",
            "apps/api/tests/test_answers.py",
        ),
        "retrieval-borne control instructions are removed before model composition",
    ),
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sandbox() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary = tempfile.TemporaryDirectory(prefix="korpus-release-mutant-")
    root = Path(temporary.name) / "repo"
    shutil.copytree(
        ROOT,
        root,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".venv-prod",
            "node_modules",
            "var",
            "reports",
            "candidate_evidence",
            "LINEAGE",
            "__pycache__",
            ".pytest_cache",
            ".coverage*",
        ),
    )
    return temporary, root


def _execute(sandbox: Path, tests: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{sandbox / 'apps/api/src'}:{sandbox}"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *tests],
        cwd=sandbox,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def run_mutant(mutant: Mutant) -> dict[str, object]:
    source_path = ROOT / mutant.path
    original = source_path.read_bytes()
    text = original.decode("utf-8")
    occurrences = text.count(mutant.old)
    if occurrences != 1:
        return {
            "id": mutant.mutant_id,
            "status": "INVALID",
            "reason": f"replacement occurrence count={occurrences}",
            "path": mutant.path,
        }
    temporary, sandbox = _sandbox()
    try:
        path = sandbox / mutant.path
        mutated = text.replace(mutant.old, mutant.new, 1).encode("utf-8")
        path.write_bytes(mutated)
        try:
            completed = _execute(sandbox, mutant.tests)
        except subprocess.TimeoutExpired:
            return {
                "id": mutant.mutant_id,
                "status": "INVALID",
                "reason": "test timeout",
                "path": mutant.path,
                "invariant": mutant.invariant,
                "source_unchanged": source_path.read_bytes() == original,
            }
        return {
            "id": mutant.mutant_id,
            "status": "KILLED" if completed.returncode else "SURVIVED",
            "path": mutant.path,
            "invariant": mutant.invariant,
            "tests": list(mutant.tests),
            "test_exit_code": completed.returncode,
            "source_sha256": sha256(original),
            "mutant_sha256": sha256(mutated),
            "source_unchanged": source_path.read_bytes() == original,
            "stdout_tail": completed.stdout[-1500:],
            "stderr_tail": completed.stderr[-1000:],
        }
    finally:
        temporary.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "reports/MUTATION_DELTA_REPORT.json")
    args = parser.parse_args()
    results = [run_mutant(mutant) for mutant in MUTANTS]
    killed = sum(item.get("status") == "KILLED" for item in results)
    survived = [str(item.get("id")) for item in results if item.get("status") == "SURVIVED"]
    invalid = [str(item.get("id")) for item in results if item.get("status") == "INVALID"]
    payload = {
        "schema": "korpus.release-mutation-delta.v1",
        "release": release_tag(),
        "source_tree_sha256": compute_source_digest(ROOT),
        "scope": "release-critical changed invariants",
        "mutants": len(results),
        "killed": killed,
        "survived": survived,
        "invalid": invalid,
        "status": "PASS" if killed == len(results) else "FAIL",
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {k: payload[k] for k in ("status", "mutants", "killed", "survived", "invalid")},
            indent=2,
        )
    )
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
