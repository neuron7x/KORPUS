from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.run_evals import REQUIRED_VALIDITY_CHECKS, validate_harness_contract

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "evals/EVALUATION_HARNESS_CONTRACT.json"


def _load() -> dict[str, object]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_evaluation_harness_names_every_validity_hazard_and_fails_closed() -> None:
    contract = validate_harness_contract(_load())
    assert set(contract["validity_checks"]) == REQUIRED_VALIDITY_CHECKS
    assert contract["independence"]["third_party"] is False
    assert contract["independence"]["production_authorization_sufficient"] is False


def test_missing_validity_hazard_is_rejected() -> None:
    mutated = copy.deepcopy(_load())
    del mutated["validity_checks"]["broken_problem_risk"]
    with pytest.raises(ValueError, match="validity checks"):
        validate_harness_contract(mutated)


def test_local_harness_cannot_claim_production_authorization() -> None:
    mutated = copy.deepcopy(_load())
    mutated["independence"]["production_authorization_sufficient"] = True
    with pytest.raises(ValueError, match="self-authorize"):
        validate_harness_contract(mutated)
