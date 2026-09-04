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
    assert policy["source_witness_is_not_execution_evidence"] is True
    assert policy["negative_control_definition_is_not_execution_evidence"] is True
    assert policy["missing_or_unobserved_execution_is_never_pass"] is True
    assert policy["production_authority"] == "OWNER_ONLY"
    assert policy["merge_authority"] == "OWNER_ONLY"

    allowed = set(policy["allowed_states"])
    for requirement in requirements:
        state = requirement["state"]
        assert state in allowed
        assert "PASS" not in state
        assert "VERIFIED" not in state


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
