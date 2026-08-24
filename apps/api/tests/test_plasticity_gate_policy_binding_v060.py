from __future__ import annotations

import hashlib
import json
from pathlib import Path

from korpus.application.plasticity_config import load_plasticity_policy
from korpus.application.plasticity_model_check import check_grid

ROOT = Path(__file__).resolve().parents[3]


def test_model_check_loads_the_exact_deployed_policy_artifact() -> None:
    path = ROOT / "config/operations/plasticity-policy.json"
    policy, digest = load_plasticity_policy(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("schema")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    assert digest == hashlib.sha256(canonical).hexdigest()
    assert policy.min_candidate_budget == raw["min_candidate_budget"]
    assert policy.high_error_rate == raw["high_error_rate"]


def test_model_check_refuses_wrong_policy_schema(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text('{"schema":"wrong"}\n', encoding="utf-8")
    try:
        load_plasticity_policy(path)
    except ValueError as exc:
        assert "unsupported plasticity policy schema" in str(exc)
    else:
        raise AssertionError("invalid policy schema was accepted")


def test_executable_reference_model_exhausts_the_release_grid() -> None:
    policy, _digest = load_plasticity_policy(ROOT / "config/operations/plasticity-policy.json")
    result = check_grid(policy)
    assert result["failures"] == []
    assert result["states_checked"] == 6912
    assert result["unique_proposals"] == 6912
    assert all(int(count) > 0 for count in result["action_counts"].values())
    assert all(result["invariants"].values())
