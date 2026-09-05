from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROPOSAL = ROOT / "docs/proposals/korpus-capability-gateway-v1"


def _load(name: str) -> dict[str, object]:
    return json.loads((PROPOSAL / name).read_text(encoding="utf-8"))


def test_base_observation_and_verification_ledger_share_one_exact_subject() -> None:
    ledger = _load("VERIFICATION_STATE.json")
    observation = _load("BASE_SYNC_OBSERVATION_2026-09-05.json")
    live_base = ledger["live_base"]

    assert isinstance(live_base, dict)
    assert observation["feature_head_sha"] == ledger["verification_candidate_commit"]
    assert observation["feature_head_sha"] == ledger["checkpoint_parent_commit"]
    assert observation["main_sha"] == live_base["observed_sha"]
    assert observation["merge_base_sha"] == live_base["merge_base_sha"]
    assert observation["feature_ahead_by"] == live_base["feature_ahead_by"]
    assert observation["feature_behind_by"] == live_base["feature_behind_by"]
    assert observation["relationship"] == live_base["relationship"]
    assert observation["acceptance_gate"] == live_base["acceptance_gate"]


def test_report_content_equivalence_cannot_false_clear_ancestry_blocker() -> None:
    ledger = _load("VERIFICATION_STATE.json")
    observation = _load("BASE_SYNC_OBSERVATION_2026-09-05.json")
    equivalence = observation["content_equivalence"]
    blockers = ledger["blocking_gates"]
    policy = ledger["verification_policy"]

    assert isinstance(equivalence, dict)
    assert isinstance(blockers, list)
    assert isinstance(policy, dict)
    assert equivalence["reports_subtree_main_sha"] == equivalence["reports_subtree_feature_sha"]
    assert equivalence["ancestry_synced"] is False
    assert policy["content_equivalence_is_not_ancestry_equivalence"] is True
    assert ledger["live_base"]["feature_behind_by"] > 0
    assert ledger["live_base"]["acceptance_gate"] == "BLOCKED"
    assert "BASE_SYNC_REQUIRED" in blockers


def test_exact_candidate_execution_evidence_is_non_oracular_when_no_steps_exist() -> None:
    ledger = _load("VERIFICATION_STATE.json")
    candidate = ledger["verification_candidate_commit"]
    execution = ledger["execution_evidence"]

    assert isinstance(execution, dict)
    assert execution["candidate_commit"] == candidate
    assert execution["exact_head_bound"] is True
    assert execution["status"] == "EXECUTION_NOT_OBSERVED"
    assert execution["steps_observed"] is False
    assert execution["logs_observed"] is False


def test_metadata_checkpoint_does_not_recursively_redefine_candidate() -> None:
    ledger = _load("VERIFICATION_STATE.json")

    assert ledger["verification_candidate_commit"] == ledger["checkpoint_parent_commit"]
    assert ledger["verification_policy"]["metadata_checkpoint_is_not_execution_evidence"] is True
    assert "pre-checkpoint" in ledger["candidate_semantics"]
