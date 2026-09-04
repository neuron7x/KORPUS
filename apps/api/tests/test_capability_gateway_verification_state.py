from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROPOSAL = ROOT / "docs/proposals/korpus-capability-gateway-v1"


def _load(name: str) -> dict[str, object]:
    return json.loads((PROPOSAL / name).read_text(encoding="utf-8"))


def test_verification_ledger_has_exact_frozen_requirement_denominator() -> None:
    frozen = _load("REQUIREMENTS.json")
    ledger = _load("VERIFICATION_STATE.json")
    frozen_requirements = frozen["requirements"]
    verification_requirements = ledger["requirements"]

    assert isinstance(frozen_requirements, list)
    assert isinstance(verification_requirements, list)
    frozen_ids = [item["id"] for item in frozen_requirements]
    verification_ids = [item["id"] for item in verification_requirements]

    assert len(frozen_ids) == 20
    assert len(set(frozen_ids)) == len(frozen_ids)
    assert verification_ids == frozen_ids
    assert ledger["denominator"] == len(frozen_ids)


def test_unobserved_execution_cannot_be_encoded_as_pass() -> None:
    ledger = _load("VERIFICATION_STATE.json")
    policy = ledger["verification_policy"]
    execution = ledger["execution_evidence"]
    requirements = ledger["requirements"]

    assert isinstance(policy, dict)
    assert isinstance(execution, dict)
    assert isinstance(requirements, list)
    assert execution["status"] == "EXECUTION_NOT_OBSERVED"
    assert execution["steps_observed"] is False
    assert execution["logs_observed"] is False
    assert execution["exact_head_bound"] is True
    assert policy["source_witness_is_not_execution_evidence"] is True
    assert policy["negative_control_definition_is_not_execution_evidence"] is True
    assert policy["missing_or_unobserved_execution_is_never_pass"] is True
    assert policy["metadata_checkpoint_is_not_execution_evidence"] is True

    allowed = set(policy["allowed_states"])
    for requirement in requirements:
        state = requirement["state"]
        assert state in allowed
        assert "PASS" not in state
        assert "VERIFIED" not in state


def test_synchronized_live_base_clears_base_sync_gate() -> None:
    ledger = _load("VERIFICATION_STATE.json")
    live_base = ledger["live_base"]
    blockers = ledger["blocking_gates"]
    cleared = ledger["cleared_gates"]

    assert isinstance(live_base, dict)
    assert isinstance(blockers, list)
    assert isinstance(cleared, list)
    assert live_base["relationship"] == "SYNCHRONIZED"
    assert live_base["feature_behind_by"] == 0
    assert live_base["merge_base_sha"] == live_base["observed_sha"]
    assert live_base["acceptance_gate"] == "CLEARED"
    assert "BASE_SYNC_REQUIRED" not in blockers
    assert "BASE_SYNC_REQUIRED" in cleared


def test_runtime_anchor_candidate_and_checkpoint_are_distinct_concepts_not_forced_values() -> None:
    ledger = _load("VERIFICATION_STATE.json")
    anchor = ledger["implementation_anchor_commit"]
    candidate = ledger["verification_candidate_commit"]
    checkpoint_parent = ledger["checkpoint_parent_commit"]
    policy = ledger["verification_policy"]
    execution = ledger["execution_evidence"]

    assert isinstance(anchor, str) and len(anchor) == 40
    assert isinstance(candidate, str) and len(candidate) == 40
    assert isinstance(checkpoint_parent, str) and len(checkpoint_parent) == 40
    assert execution["candidate_commit"] == candidate
    assert policy["runtime_anchor_is_not_candidate_identity"] is True
    assert policy["metadata_checkpoint_is_not_execution_evidence"] is True
    # The concepts are independent even when the current runtime anchor is exactly the
    # candidate that GitHub attempted to execute. Equality is neither required nor forbidden.
    assert "may equal" in ledger["anchor_semantics"]


def test_owner_authorization_is_cleared_without_promoting_technical_gates() -> None:
    ledger = _load("VERIFICATION_STATE.json")
    owner = ledger["owner_authority"]
    blockers = ledger["blocking_gates"]
    cleared = ledger["cleared_gates"]

    assert isinstance(owner, dict)
    assert owner["merge_authorization"] == "GRANTED_CONDITIONAL_ON_TECHNICAL_VALIDITY"
    assert owner["production_authority"] == "NOT_GRANTED_BY_THIS_RECORD"
    assert "OWNER_APPROVAL_NOT_GRANTED" not in blockers
    assert "OWNER_APPROVAL_GRANTED" in cleared


def test_only_observed_unresolved_gates_block_merge_readiness() -> None:
    ledger = _load("VERIFICATION_STATE.json")
    blockers = ledger["blocking_gates"]

    assert isinstance(blockers, list)
    assert set(blockers) == {
        "EXECUTION_NOT_OBSERVED",
        "CLEAN_ROOM_REPRODUCTION_NOT_EXECUTED",
        "FRESH_CONTEXT_VERIFICATION_NOT_EXECUTED",
    }
    encoded = json.dumps(ledger, sort_keys=True)
    assert '"status": "PASS"' not in encoded
    assert '"status": "READY_FOR_OWNER_APPROVAL"' not in encoded


def test_clean_room_and_fresh_context_are_bound_to_current_candidate_without_false_pass() -> None:
    ledger = _load("VERIFICATION_STATE.json")
    candidate = ledger["verification_candidate_commit"]
    clean_room = ledger["clean_room_evidence"]
    fresh = ledger["fresh_context_evidence"]

    assert isinstance(clean_room, dict)
    assert isinstance(fresh, dict)
    assert clean_room["status"] == "CLEAN_ROOM_REPRODUCTION_NOT_EXECUTED"
    assert clean_room["candidate_commit"] == candidate
    assert clean_room["test_command_executed"] is False
    assert fresh["status"] == "FRESH_CONTEXT_VERIFICATION_NOT_EXECUTED"
    assert fresh["candidate_commit"] == candidate


def test_runner_probe_is_diagnostic_only_and_cannot_clear_execution_blocker() -> None:
    ledger = _load("VERIFICATION_STATE.json")
    policy = ledger["verification_policy"]
    execution = ledger["execution_evidence"]
    probe = ledger["runner_assignment_probe"]
    blockers = ledger["blocking_gates"]

    assert isinstance(policy, dict)
    assert isinstance(execution, dict)
    assert isinstance(probe, dict)
    assert isinstance(blockers, list)
    assert policy["diagnostic_probe_is_not_candidate_verification"] is True
    assert probe["status"] == "PRE_RUNNER_EXECUTION_FAILURE_CONFIRMED"
    assert probe["candidate_verification"] is False
    assert probe["external_actions_used"] is False
    assert execution["status"] == "EXECUTION_NOT_OBSERVED"
    assert "EXECUTION_NOT_OBSERVED" in blockers

    jobs = probe["jobs"]
    assert isinstance(jobs, list)
    assert {job["name"] for job in jobs} == {
        "runner-probe-ubuntu-latest",
        "runner-probe-ubuntu-24.04",
    }
    assert all(job["conclusion"] == "failure" for job in jobs)
    assert all(job["steps_observed"] is False for job in jobs)
    assert all(job["logs_observed"] is False for job in jobs)


def test_every_verification_witness_is_repository_local_and_exists() -> None:
    ledger = _load("VERIFICATION_STATE.json")
    requirements = ledger["requirements"]

    assert isinstance(requirements, list)
    for requirement in requirements:
        code = requirement["code_witnesses"]
        controls = requirement["control_witnesses"]
        state = requirement["state"]
        assert isinstance(code, list)
        assert isinstance(controls, list)
        assert controls
        if state == "SOURCE_DEFINED_EXECUTION_NOT_OBSERVED":
            assert code

        for witness in [*code, *controls]:
            path = Path(witness)
            assert not path.is_absolute()
            assert ".." not in path.parts
            assert (ROOT / path).is_file(), witness
