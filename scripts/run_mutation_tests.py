#!/usr/bin/env python3
"""Deterministic first-order mutation gate for critical KORPUS invariants.

This deliberately mutates security- and evidence-critical predicates and proves
that the focused verification suite kills every mutant. It uses only stdlib and
pytest, so it runs in constrained/offline CI environments.
"""
from __future__ import annotations

import argparse
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
    Mutant(
        "M12_REMOTE_ANCHOR_MAC_BYPASS",
        "apps/api/src/korpus/infrastructure/audit_anchor.py",
        "if not hmac.compare_digest(expected, supplied_mac):",
        "if False:",
        ("apps/api/tests/test_http_audit_anchor.py::test_remote_anchor_detects_payload_tampering",),
    ),
    Mutant(
        "M13_OPERATIONAL_LEAKAGE_GATE_INVERTED",
        "apps/api/src/korpus/application/operations.py",
        '<= int(eval_policy["maximum_leakage_failures"]),',
        '>= int(eval_policy["maximum_leakage_failures"]),',
        ("apps/api/tests/test_operations.py::test_operational_gate_fails_closed_on_trust_regression",),
    ),
    Mutant(
        "M14_SEMANTIC_OUTAGE_FALLBACK",
        "apps/api/src/korpus/application/retrieval.py",
        'raise RetrievalUnavailable("required semantic retrieval is unavailable") from exc',
        'semantic_hits = []',
        ("apps/api/tests/test_semantic_integration.py::test_required_semantic_failure_never_silently_falls_back_to_lexical",),
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
        original = target.read_text(encoding="utf-8")
        count = original.count(mutant.old)
        if count == 0:
            return {"id": mutant.id, "status": "INVALID", "reason": "mutation target not found"}
        target.write_text(original.replace(mutant.old, mutant.new), encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(sandbox / "apps/api/src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONHASHSEED"] = "0"
        command = [sys.executable, "-m", "pytest", "-q", "--maxfail=1", *mutant.tests]
        completed = subprocess.run(
            command,
            cwd=sandbox,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=45,
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


def summarize(results: list[dict[str, object]], *, shard_index: int | None, shard_count: int) -> dict[str, object]:
    killed = sum(result["status"] == "KILLED" for result in results)
    valid = sum(result["status"] in {"KILLED", "SURVIVED"} for result in results)
    score = killed / valid if valid else 0.0
    return {
        "schema_version": 2,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "mutants": len(results),
        "valid_mutants": valid,
        "killed": killed,
        "survived": [result["id"] for result in results if result["status"] == "SURVIVED"],
        "invalid": [result["id"] for result in results if result["status"] == "INVALID"],
        "mutation_score": score,
        "results": results,
    }


def merge_shards(shard_count: int) -> dict[str, object]:
    shard_dir = ROOT / "var/mutation-shards"
    shard_paths = [shard_dir / f"shard-{index}-of-{shard_count}.json" for index in range(shard_count)]
    missing = [str(path) for path in shard_paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing mutation shards: {missing}")
    results: list[dict[str, object]] = []
    for path in shard_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("shard_count", -1)) != shard_count:
            raise RuntimeError(f"shard count mismatch in {path}")
        results.extend(payload.get("results", []))
    expected = {mutant.id for mutant in MUTANTS}
    actual = {str(result.get("id")) for result in results}
    if actual != expected or len(results) != len(MUTANTS):
        raise RuntimeError(
            f"mutation shard coverage mismatch: missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    ordered = sorted(results, key=lambda item: str(item["id"]))
    report = summarize(ordered, shard_index=None, shard_count=shard_count)
    report["mutants"] = len(MUTANTS)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--merge", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.shard_count < 1:
        raise SystemExit("--shard-count must be >= 1")
    if args.merge:
        report = merge_shards(args.shard_count)
        output = ROOT / "var/mutation-report.json"
    else:
        if args.shard_index is None:
            shard_index = 0
        else:
            shard_index = args.shard_index
        if not 0 <= shard_index < args.shard_count:
            raise SystemExit("--shard-index must satisfy 0 <= index < shard-count")
        selected = list(MUTANTS[shard_index::args.shard_count])
        results = [run_mutant(mutant) for mutant in selected]
        report = summarize(
            results,
            shard_index=shard_index if args.shard_count > 1 else None,
            shard_count=args.shard_count,
        )
        if args.shard_count > 1:
            output = ROOT / "var/mutation-shards" / f"shard-{shard_index}-of-{args.shard_count}.json"
        else:
            output = ROOT / "var/mutation-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, indent=2))
    expected = len(MUTANTS) if args.merge or args.shard_count == 1 else len(report["results"])
    return 0 if report["mutation_score"] == 1.0 and report["valid_mutants"] == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
