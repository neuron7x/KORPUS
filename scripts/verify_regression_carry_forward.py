#!/usr/bin/env python3
"""Verify bounded carry-forward of full regression evidence across an assurance-only delta.

Production gates remain source-exact and do not consume this artifact.  This verifier exists
only for the weighted engineering-readiness assessment: it proves that the pre-existing
product runtime surface is byte-identical to the baseline and that every allowed delta is
explicitly enumerated and covered by a fresh targeted test campaign.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.junit_contracts import junit_counts  # noqa: E402
from korpus.application.provenance import (  # noqa: E402
    EVIDENCE_SOURCE_PATHS,
    _digest_candidates,
    compute_source_digest,
)
from korpus.release import RELEASE_TAG  # noqa: E402


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _current_records(root: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    for path in _digest_candidates(root, EVIDENCE_SOURCE_PATHS):
        rel = path.relative_to(root).as_posix()
        records[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return records


def _baseline_records(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for record in payload.get("records", []):
        if not isinstance(record, dict):
            raise ValueError("baseline manifest record must be an object")
        path, digest = record.get("path"), record.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            raise ValueError("baseline manifest record requires path and sha256")
        result[path] = digest
    return result


def diff_records(
    old: dict[str, str], new: dict[str, str]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    added = tuple(sorted(set(new) - set(old)))
    removed = tuple(sorted(set(old) - set(new)))
    modified = tuple(sorted(path for path in set(old) & set(new) if old[path] != new[path]))
    return added, removed, modified


def junit_summary(path: Path) -> dict[str, int]:
    try:
        return junit_counts(ET.parse(path).getroot())
    except (ET.ParseError, OSError, ValueError):
        return {"tests": 0, "failures": 1, "errors": 1, "skipped": 0}


def evaluate(policy: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    baseline_manifest = _json(root / str(policy["baseline_manifest"]))
    baseline_backend = _json(root / str(policy["baseline_backend_report"]))
    baseline_mutation = _json(root / str(policy["baseline_mutation_gate"]))
    old = _baseline_records(baseline_manifest)
    new = _current_records(root)
    added, removed, modified = diff_records(old, new)
    changed = set(added) | set(modified)
    allowed = {
        str(item) for item in policy.get("allowed_added_or_modified_evidence_source_paths", [])
    }
    allowed_removed = {
        str(item) for item in policy.get("allowed_removed_evidence_source_paths", [])
    }
    forbidden_prefixes = tuple(
        str(item) for item in policy.get("forbidden_runtime_change_prefixes", [])
    )
    junit_path = root / str(policy["targeted_junit"])
    junit = (
        junit_summary(junit_path)
        if junit_path.is_file()
        else {"tests": 0, "failures": 1, "errors": 0, "skipped": 0}
    )
    checks = {
        "baseline_manifest_identity": baseline_manifest.get("source_tree_sha256")
        == policy.get("baseline_source_tree_sha256"),
        "baseline_backend_pass": baseline_backend.get("status") == "PASS"
        and baseline_backend.get("failed") == 0
        and baseline_backend.get("errors") == 0,
        "baseline_backend_identity": baseline_backend.get("source_tree_sha256")
        == policy.get("baseline_source_tree_sha256"),
        "baseline_mutation_pass": baseline_mutation.get("status") == "PASS"
        and baseline_mutation.get("killed")
        == baseline_mutation.get("valid_mutants")
        == baseline_mutation.get("mutants"),
        "baseline_mutation_identity": baseline_mutation.get("source_tree_sha256")
        == policy.get("baseline_source_tree_sha256"),
        "no_unexpected_added_or_modified_paths": changed <= allowed,
        "no_unexpected_removed_paths": set(removed) <= allowed_removed,
        "no_forbidden_runtime_changes": not any(
            path.startswith(forbidden_prefixes) for path in changed
        ),
        "targeted_junit_present": junit_path.is_file(),
        "targeted_tests_minimum": junit["tests"] >= int(policy.get("minimum_targeted_tests", 0)),
        "targeted_tests_clean": junit["failures"] == 0 and junit["errors"] == 0,
        "target_release": str(policy.get("target_release")) == RELEASE_TAG,
    }
    failures = [name for name, ok in checks.items() if not ok]
    return {
        "schema": "korpus.regression-carry-forward-evidence.v1",
        "status": "PASS" if not failures else "FAIL",
        "baseline_release": policy.get("baseline_release"),
        "baseline_source_tree_sha256": policy.get("baseline_source_tree_sha256"),
        "target_release": RELEASE_TAG,
        "target_source_tree_sha256": compute_source_digest(root),
        "checks": checks,
        "failures": failures,
        "delta": {"added": list(added), "modified": list(modified), "removed": list(removed)},
        "targeted_junit": junit,
        "scope": "ENGINEERING_READINESS_ONLY_NOT_PRODUCTION_SOURCE_BINDING",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "config/assurance/regression-carry-forward-v0.7.0.json",
    )
    # Типовий вихід — чернетка, а НЕ релізний звіт. Виміряно 01.09.2026: щоб дізнатись,
    # чи ця ціль узагалі запускається, я її запустила — і вона перезаписала
    # `reports/release/v0.7.0/REGRESSION_CARRY_FORWARD.json`, тобто той самий артефакт,
    # який `build_readiness_947_evidence.py` читає як доказ. Перевірка, що пише в те, що
    # перевіряє, робить розбіжність між твердженням і станом непомітною: після прогону
    # вони збігаються завжди. Писати в реліз тепер можна лише назвавши шлях явно.
    parser.add_argument("--out", type=Path, default=ROOT / "var/regression-carry-forward.json")
    args = parser.parse_args()
    payload = evaluate(_json(args.policy.resolve()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
