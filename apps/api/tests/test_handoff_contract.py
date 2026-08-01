from __future__ import annotations

import importlib.util
from pathlib import Path


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
