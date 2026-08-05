from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_local_handoff_contract_is_consistent_with_code_and_evidence() -> None:
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts" / "verify_handoff_contract.py"
    spec = importlib.util.spec_from_file_location("verify_handoff_contract", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.verify()
    assert result["status"] == "PASS"
    assert result["weights_sum"] == 1.0
    assert result["next_iterations"] == 10
    assert result["next_integrations"] == 7
    assert result["production_authorized"] is False


def test_the_iteration_register_cannot_claim_completion_inside_this_repository() -> None:
    """The gate used to enforce that the plan stay unexecuted.

    `verify_handoff_contract.py` required `status == "PLANNED_NOT_EXECUTED"`, so shipping
    eight of the ten items failed it and the only way past was to leave the register
    saying nothing had been done. It read PLANNED — NOT EXECUTED for a day while eight
    items had code, tests and mutants — the same defect the closure counts had, failing
    in the direction that looks modest rather than the direction that looks finished,
    which is why nobody catches it.

    What the contract has to hold instead is that no item declares itself finished:
    every acceptance list here ends in evidence from a cluster, an assessor, an
    annotated corpus or a risk owner, and none of those is reachable from this tree.
    """
    register = json.loads(
        (ROOT / "handoff/machine/next_iterations.json").read_text(encoding="utf-8")
    )

    assert register["status"] in {"PLANNED_NOT_EXECUTED", "PARTIALLY_EXECUTED"}
    assert len(register["items"]) == 10
    for item in register["items"]:
        assert item.get("status") in {"NOT_EXECUTED", "PARTIALLY_EXECUTED"}, (
            f"{item['id']} claims completion; its acceptance list ends outside this tree"
        )
        if item["status"] == "PARTIALLY_EXECUTED":
            assert item.get("execution_note"), (
                f"{item['id']} is marked started with nothing saying what was done "
                "and what remains, which is a status nobody can act on"
            )
