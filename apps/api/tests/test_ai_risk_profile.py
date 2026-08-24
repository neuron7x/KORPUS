from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "config/governance/ai-risk-profile-v1.json"


def test_ai_risk_profile_has_killable_owned_evidenced_risks() -> None:
    payload = json.loads(PROFILE.read_text(encoding="utf-8"))
    assert payload["schema"] == "korpus.ai-risk-profile.v1"
    assert payload["system_id"] == "KORPUS"
    risks = payload["risks"]
    assert risks and len({risk["id"] for risk in risks}) == len(risks)
    for risk in risks:
        assert risk["severity"] in {"P0", "P1", "P2"}
        assert risk["owner_role"]
        assert risk["metric"]
        assert risk["kill_predicate"]
        assert risk["controls"]
        assert risk["evidence_required"]


def test_ai_risk_profile_has_no_self_authorizing_p0_or_p1_path() -> None:
    payload = json.loads(PROFILE.read_text(encoding="utf-8"))
    acceptance = payload["risk_acceptance"]
    assert "external" in acceptance["P0"]
    assert "evidence" in acceptance["P1"]
