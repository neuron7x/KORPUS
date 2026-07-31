#!/usr/bin/env python3
"""Deterministic first-order mutation gate for critical KORPUS invariants.

This deliberately mutates security- and evidence-critical predicates and proves
that the focused verification suite kills every mutant. It uses only stdlib and
pytest, so it runs in constrained/offline CI environments.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Mutant:
    id: str
    file: str
    old: str
    new: str
    tests: tuple[str, ...]


MUTANTS = (
    Mutant(
        "M01_CLEARANCE_INVERSION",
        "apps/api/src/korpus/application/policy.py",
        "if identity.clearance < document.access_tier:",
        "if identity.clearance > document.access_tier:",
        ("apps/api/tests/test_more_edges.py::test_access_tier_parse_and_document_decision",),
    ),
    Mutant(
        "M02_QUERY_INJECTION_BYPASS",
        "apps/api/src/korpus/application/answer_query.py",
        "return any(pattern.search(normalized) for pattern in INJECTION_PATTERNS)",
        "return False",
        ("apps/api/tests/test_answers.py::test_query_control_injection_abstains_before_retrieval",),
    ),
    Mutant(
        "M03_SUPPORT_MAX_INSTEAD_OF_MIN",
        "apps/api/src/korpus/application/answer_query.py",
        "support_score = min(item.score, candidate.query_coverage)",
        "support_score = max(item.score, candidate.query_coverage)",
        ("apps/api/tests/test_answers.py::test_approved_document_produces_exact_claim_bound_citation",),
    ),
    Mutant(
        "M04_AUDIT_PREDECESSOR_BYPASS",
        "apps/api/src/korpus/infrastructure/repository.py",
        'if row["previous_hash"] != previous_hash or not hmac.compare_digest(expected_hash, row["event_hash"]):',
        'if not hmac.compare_digest(expected_hash, row["event_hash"]):',
        ("apps/api/tests/test_audit.py::test_audit_chain_rejects_re_signed_broken_predecessor_link",),
    ),
    Mutant(
        "M05_SQL_CLEARANCE_FILTER_REMOVED",
        "apps/api/src/korpus/infrastructure/repository.py",
        ".where(documents.c.access_tier <= int(identity.clearance))",
        ".where(documents.c.access_tier <= 3)",
        ("apps/api/tests/test_access_control.py::test_access_tier_is_enforced_in_repository_even_for_public_classification",),
    ),
    Mutant(
        "M06_RELEASE_SCOPE_BROADENED",
        "apps/api/src/korpus/infrastructure/repository.py",
        "retrievable = self.list_retrievable_spans(identity, corpus_ids, as_of)",
        "retrievable = self.list_retrievable_spans(identity.model_copy(update={'clearance': AccessTier.RESTRICTED, 'corpora': frozenset({'public', 'restricted-demo'})}), frozenset({'public', 'restricted-demo'}), as_of)",
        ("apps/api/tests/test_access_control.py::test_restricted_corpus_update_does_not_change_public_release",),
    ),
    Mutant(
        "M07_SUPERSESSION_EDGE_DROPPED",
        "apps/api/src/korpus/application/ingestion.py",
        "**version_data.model_dump(),",
        "**version_data.model_dump(exclude={\"supersedes_version_id\"}),",
        ("apps/api/tests/test_versioning.py::test_new_approved_version_supersedes_old_version_in_current_retrieval",),
    ),
    Mutant(
        "M08_OBJECT_HASH_CHECK_REMOVED",
        "apps/api/src/korpus/infrastructure/object_store.py",
        'if hashlib.sha256(content).hexdigest() != source_hash:\n            raise ValueError("source hash does not match content")',
        "if False:\n            raise ValueError(\"source hash does not match content\")",
        ("apps/api/tests/test_more_edges.py::test_object_store_is_content_addressed_atomic_and_filename_independent",),
    ),
    Mutant(
        "M09_CLASSIFICATION_GATE_REMOVED",
        "apps/api/src/korpus/application/policy.py",
        "if document.classification.minimum_tier > identity.clearance:",
        "if False:",
        ("apps/api/tests/test_more_edges.py::test_access_tier_parse_and_document_decision",),
    ),
    Mutant(
        "M10_AUDIT_HEAD_CHECK_REMOVED",
        "apps/api/src/korpus/infrastructure/repository.py",
        "if head_sequence != len(rows) or head_hash != previous_hash:",
        "if False:",
        ("apps/api/tests/test_audit.py::test_audit_anchor_detects_tail_truncation",),
    ),
    Mutant(
        "M11_REVIEW_SEPARATION_BYPASS",
        "apps/api/src/korpus/application/ingestion.py",
        "if self.review_separation_required:",
        "if False:",
        ("apps/api/tests/test_state_machine.py::test_controlled_review_separation_is_subject_based",),
    ),
)


def copy_repository(destination: Path) -> None:
    ignored = shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", ".coverage", "var", "dist", "node_modules", ".venv")
    shutil.copytree(ROOT, destination, ignore=ignored, dirs_exist_ok=True)


def run_mutant(mutant: Mutant) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"korpus-{mutant.id.lower()}-") as temp:
        sandbox = Path(temp) / "repo"
        copy_repository(sandbox)
        target = sandbox / mutant.file
        source = target.read_text(encoding="utf-8")
        count = source.count(mutant.old)
        if count == 0:
            return {"id": mutant.id, "status": "INVALID", "reason": "mutation target not found"}
        target.write_text(source.replace(mutant.old, mutant.new), encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(sandbox / "apps/api/src")
        command = [sys.executable, "-m", "pytest", "-q", "--maxfail=1", *mutant.tests]
        completed = subprocess.run(
            command,
            cwd=sandbox,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
            check=False,
        )
        killed = completed.returncode != 0
        return {
            "id": mutant.id,
            "file": mutant.file,
            "status": "KILLED" if killed else "SURVIVED",
            "returncode": completed.returncode,
            "target_occurrences": count,
            "tests": list(mutant.tests),
            "output_tail": completed.stdout[-3000:],
        }


def main() -> int:
    results = [run_mutant(mutant) for mutant in MUTANTS]
    killed = sum(result["status"] == "KILLED" for result in results)
    valid = sum(result["status"] in {"KILLED", "SURVIVED"} for result in results)
    score = killed / valid if valid else 0.0
    report = {
        "schema_version": 1,
        "mutants": len(MUTANTS),
        "valid_mutants": valid,
        "killed": killed,
        "survived": [result["id"] for result in results if result["status"] == "SURVIVED"],
        "invalid": [result["id"] for result in results if result["status"] == "INVALID"],
        "mutation_score": score,
        "results": results,
    }
    output = ROOT / "var/mutation-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 0 if score == 1.0 and valid == len(MUTANTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
