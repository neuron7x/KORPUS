from __future__ import annotations

import json
from pathlib import Path

from scripts import run_inference_security_gate as gate

ROOT = Path(__file__).resolve().parents[3]


def _profile() -> dict[str, object]:
    return {
        "gate_id": "inference_security",
        "evidence_class": "INTERNAL_ADVERSARIAL",
        "timeout_seconds": 300,
        "attack_families": ["direct_prompt_injection", "egress_leakage"],
        "pytest_targets": ["apps/api/tests/test_model_egress.py"],
        "family_targets": {
            "direct_prompt_injection": ["apps/api/tests/test_model_egress.py"],
            "egress_leakage": ["apps/api/tests/test_model_egress.py"],
        },
    }


def test_inference_security_profile_is_fail_closed_on_empty_or_duplicate_scope() -> None:
    profile = _profile()
    checks, _, _ = gate._profile_checks(profile)
    assert all(checks.values())

    profile["attack_families"] = []
    profile["family_targets"] = {}
    checks, _, _ = gate._profile_checks(profile)
    assert checks["attack_families_nonempty"] is False

    profile = _profile()
    profile["pytest_targets"] = ["apps/api/tests/test_model_egress.py"] * 2
    checks, _, _ = gate._profile_checks(profile)
    assert checks["pytest_targets_unique"] is False


def test_inference_security_profile_rejects_unmapped_attack_family() -> None:
    profile = _profile()
    profile["family_targets"] = {
        "direct_prompt_injection": ["apps/api/tests/test_model_egress.py"]
    }
    checks, _, _ = gate._profile_checks(profile)
    assert checks["family_target_mapping_complete"] is False


def test_inference_security_profile_rejects_missing_test_target() -> None:
    profile = _profile()
    profile["pytest_targets"] = ["apps/api/tests/does_not_exist.py"]
    checks, _, _ = gate._profile_checks(profile)
    assert checks["pytest_targets_exist"] is False


def test_repository_inference_security_profile_has_executable_scope() -> None:
    profile = json.loads((ROOT / "config/assurance/inference-security-v1.json").read_text(encoding="utf-8"))
    checks, families, targets = gate._profile_checks(profile)
    assert all(checks.values()), checks
    assert len(families) == 7
    assert len(targets) == 8
    assert "apps/api/tests/test_indirect_prompt_injection_boundary.py" in targets


def test_production_assurance_has_a_tracked_inference_security_generator() -> None:
    script = ROOT / "scripts/run_inference_security_gate.py"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "compute_source_digest" in text
    assert 'gate_payload(\n        "inference_security"' in text
    assert "--junitxml=" in text
