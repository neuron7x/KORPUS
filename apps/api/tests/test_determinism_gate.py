from __future__ import annotations

import pytest

from scripts.run_determinism_gate import stable, validate_report


def report(hashes: list[str], verdict: str = "PASS"):
    artifact = {"sha256": hashes, "stable": len(set(hashes)) == 1}
    return {
        "schema": "korpus.determinism-assurance.v1", "candidate_commit": "a" * 40,
        "repetitions": 3, "artifacts": {"eval_report": artifact, "system_manifest": artifact},
        "environment": {}, "production_authorized": False, "verdict": verdict,
    }


def test_hash_stability_requires_every_repetition_to_match():
    same = ["a" * 64] * 3
    assert stable(same, 3)
    assert not stable(["a" * 64, "b" * 64, "a" * 64], 3)
    assert not stable(same[:2], 3)


def test_validator_rejects_changed_hash_and_false_pass():
    changed = ["a" * 64, "b" * 64, "a" * 64]
    with pytest.raises(ValueError, match="DET-VERDICT-CONTRADICTION"):
        validate_report(report(changed, "PASS"))


def test_validator_rejects_production_authorization():
    payload = report(["a" * 64] * 3)
    payload["production_authorized"] = True
    with pytest.raises(ValueError, match="DET-PRODUCTION-AUTHORIZATION"):
        validate_report(payload)
