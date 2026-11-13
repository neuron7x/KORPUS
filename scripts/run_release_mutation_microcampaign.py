#!/usr/bin/env python3
"""Sandboxed first-order mutation campaign for release-critical invariants."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT), str(ROOT / "scripts")]

from korpus.application.provenance import compute_source_digest  # noqa: E402
from mutation_probe_execution import SuiteExecution, mutation_outcome, run_suite  # noqa: E402
from release_mutation_summary import campaign_summary  # noqa: E402

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


def _execute(sandbox: Path, tests: tuple[str, ...]) -> SuiteExecution:
    return run_suite(120, sandbox, test_paths=tests, stop_on_failure=False)


def _measure(sandbox: Path, mutant: Mutant) -> dict[str, object]:
    path = sandbox / mutant.path
    original = path.read_bytes()
    mutated = original.decode("utf-8").replace(mutant.old, mutant.new, 1).encode("utf-8")
    baseline = _execute(sandbox, mutant.tests)
    result: dict[str, object] = {
        "baseline": baseline.receipt(),
        "execution": None,
        "test_exit_code": None,
        "source_sha256": sha256(original),
        "mutant_sha256": sha256(mutated),
    }
    if baseline.status != "PASSED":
        return {**result, "status": "INVALID", "reason": f"BASELINE_{baseline.reason}"}
    if path.read_bytes() != original:
        return {**result, "status": "INVALID", "reason": "BASELINE_CHANGED_SOURCE"}
    path.write_bytes(mutated)
    execution = _execute(sandbox, mutant.tests)
    status, reason = mutation_outcome(baseline, execution, require_complete=True)
    return {
        **result,
        "status": "INVALID" if status == "INCONCLUSIVE" else status,
        "reason": reason,
        "execution": execution.receipt(),
        "test_exit_code": execution.returncode,
        "stdout_tail": execution.stdout_tail,
        "stderr_tail": execution.stderr_tail,
    }


def run_mutant(mutant: Mutant) -> dict[str, object]:
    source_path = ROOT / mutant.path
    original = source_path.read_bytes()
    occurrences = original.decode("utf-8").count(mutant.old)
    identity: dict[str, object] = {
        "id": mutant.mutant_id,
        "path": mutant.path,
        "invariant": mutant.invariant,
        "tests": list(mutant.tests),
    }
    if occurrences != 1:
        return {
            **identity,
            "status": "INVALID",
            "reason": f"replacement occurrence count={occurrences}",
        }
    temporary, sandbox = _sandbox()
    try:
        if (sandbox / mutant.path).read_bytes() != original:
            return {**identity, "status": "INVALID", "reason": "SANDBOX_SOURCE_DRIFT"}
        result = _measure(sandbox, mutant)
        unchanged = source_path.read_bytes() == original
        if not unchanged:
            result.update(status="INVALID", reason="ORIGINAL_SOURCE_CHANGED")
        return {**identity, **result, "source_unchanged": unchanged}
    finally:
        temporary.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "reports/MUTATION_DELTA_REPORT.json")
    args = parser.parse_args()
    results = [run_mutant(mutant) for mutant in MUTANTS]
    payload = {
        "schema": "korpus.release-mutation-delta.v1",
        "release": release_tag(),
        "source_tree_sha256": compute_source_digest(ROOT),
        "scope": "release-critical changed invariants",
        **campaign_summary(results),
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
