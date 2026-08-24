"""Grouped evaluation of PEC metamorphic observations."""
from __future__ import annotations

from collections import defaultdict

from korpus.application.pec_metamorphic_rules import metamorphic_issues

BINDING_KEYS = ("source_digest", "corpus_release_id", "evaluation_protocol_sha256", "answer_calibration_id")


def _groups(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("pair_id", ""))].append(row)
    return grouped


def _binding_report(bindings: set[tuple[str, ...]]) -> tuple[bool, dict[str, str] | None, list[dict[str, object]]]:
    if len(bindings) != 1:
        return False, None, [{"pair_id": "*", "issues": ["artifact_binding_mismatch"]}]
    binding = next(iter(bindings))
    complete = all(binding)
    failures = [] if complete else [{"pair_id": "*", "issues": ["artifact_binding_incomplete"]}]
    return complete, dict(zip(BINDING_KEYS, binding, strict=True)), failures


def evaluate_metamorphic_pairs(rows: list[dict[str, object]], minimum_pairs: int) -> dict[str, object]:
    grouped = _groups(rows)
    failures: list[dict[str, object]] = []
    bindings: set[tuple[str, ...]] = set()
    checked = 0
    for pair_id, variants in sorted(grouped.items()):
        base = next((row for row in variants if row.get("variant") == "base"), None)
        transformed = [row for row in variants if row.get("variant") == "transformed"]
        if not pair_id or base is None or not transformed:
            failures.append({"pair_id": pair_id, "issues": ["incomplete_pair"]})
            continue
        bindings.update(tuple(str(row.get(key, "")) for key in BINDING_KEYS) for row in [base, *transformed])
        for row in transformed:
            checked += 1
            issues = metamorphic_issues(base, row)
            if issues:
                failures.append({"pair_id": pair_id, "transformation_id": row.get("transformation_id"), "issues": issues})
    binding_complete, binding, binding_failures = _binding_report(bindings)
    failures.extend(binding_failures)
    status = "FAIL" if failures else ("PASS" if checked >= minimum_pairs else "UNKNOWN")
    return {
        "status": status, "pairs": len(grouped), "transforms_checked": checked,
        "minimum_pairs": minimum_pairs, "binding": binding,
        "binding_completeness": "PASS" if binding_complete else "UNKNOWN",
        "failures": failures[:100],
    }
