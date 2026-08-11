from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from korpus.application.tevv_evidence import evaluate_tevv_ledger

ROOT = Path(__file__).resolve().parents[3]
PROFILE = json.loads((ROOT / "config/assurance/tevv-production-v1.json").read_text(encoding="utf-8"))


def _evidence() -> dict:
    families = PROFILE["required_attack_families"]
    return {
        "observation_ledger": [
            {
                "id": f"obs-{index}", "passed": True,
                "citation_failures": 0, "leakage_failures": 0, "determinism_failures": 0,
                "attack_families": [families[index % len(families)]],
            }
            for index in range(220)
        ],
        "null_control_ledger": [
            {"id": f"null-{index}", "false_accept": False}
            for index in range(20)
        ],
    }


def test_tevv_aggregates_are_recomputed_from_case_ledgers() -> None:
    result = evaluate_tevv_ledger(_evidence(), PROFILE)
    assert all(result["checks"].values()), result
    assert result["metrics"] == {
        "observations": 220, "passed": 220,
        "citation_failures": 0, "leakage_failures": 0, "determinism_failures": 0,
        "null_controls": 20, "null_control_false_accepts": 0,
        "attack_families": sorted(PROFILE["required_attack_families"]),
    }


def test_signed_summary_counters_without_observation_ledger_are_not_evidence() -> None:
    legacy = {
        "observations": 1000, "passed": 1000, "citation_failures": 0,
        "leakage_failures": 0, "determinism_failures": 0,
        "null_controls": 100, "null_control_false_accepts": 0,
        "attack_families": PROFILE["required_attack_families"],
    }
    result = evaluate_tevv_ledger(legacy, PROFILE)
    assert result["checks"]["observation_ledger_structured"] is False
    assert result["metrics"]["observations"] == 0


def test_missing_attack_family_cannot_be_repaired_by_declared_summary() -> None:
    evidence = _evidence()
    missing = PROFILE["required_attack_families"][-1]
    evidence["observation_ledger"] = [
        row for row in evidence["observation_ledger"] if missing not in row["attack_families"]
    ]
    evidence["attack_families"] = PROFILE["required_attack_families"]
    result = evaluate_tevv_ledger(evidence, PROFILE)
    assert result["checks"]["required_attack_families_covered"] is False
    assert result["checks"]["declared_aggregates_consistent"] is False


def test_duplicate_observation_ids_fail_closed() -> None:
    evidence = _evidence()
    evidence["observation_ledger"][1]["id"] = evidence["observation_ledger"][0]["id"]
    assert evaluate_tevv_ledger(evidence, PROFILE)["checks"]["observation_ids_unique"] is False


def test_failure_counts_come_from_rows_not_top_level_claims() -> None:
    evidence = _evidence()
    evidence["observation_ledger"][0]["leakage_failures"] = 1
    evidence["leakage_failures"] = 0
    result = evaluate_tevv_ledger(evidence, PROFILE)
    assert result["metrics"]["leakage_failures"] == 1
    assert result["checks"]["declared_aggregates_consistent"] is False


def test_null_false_accepts_are_recomputed_from_null_ledger() -> None:
    evidence = _evidence()
    evidence["null_control_ledger"][0]["false_accept"] = True
    evidence["null_control_false_accepts"] = 0
    result = evaluate_tevv_ledger(evidence, PROFILE)
    assert result["metrics"]["null_control_false_accepts"] == 1
    assert result["checks"]["declared_aggregates_consistent"] is False


def test_malformed_row_does_not_count_toward_observation_floor() -> None:
    evidence = _evidence()
    broken = deepcopy(evidence["observation_ledger"][0])
    broken["passed"] = "yes"
    evidence["observation_ledger"].append(broken)
    result = evaluate_tevv_ledger(evidence, PROFILE)
    assert result["checks"]["observation_ledger_structured"] is False
    assert result["metrics"]["observations"] == 220
