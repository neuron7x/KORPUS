from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from korpus.application.production_hard_predicates import (
    evaluate_hard_predicates,
    load_hard_predicate_profile,
)

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "config/assurance/production-hard-predicates-v1.json"


def _release_truth_module():
    path = ROOT / "scripts/generate_release_truth.py"
    spec = importlib.util.spec_from_file_location("generate_release_truth_tested", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_software_artifact_is_internal_blocker(tmp_path: Path) -> None:
    profile = load_hard_predicate_profile(PROFILE)
    mutated = json.loads(json.dumps(profile))
    mutated["predicates"][0]["software_artifacts"].append("definitely/missing/proof-path")
    states = evaluate_hard_predicates(ROOT, mutated, {})
    first = next(state for state in states if state.predicate_id == "external_independent_redteam")
    assert first.software_ready is False
    assert "definitely/missing/proof-path" in first.missing_software_artifacts
    assert first.production_satisfied is False


def test_release_truth_rejects_stale_hard_predicate_report(monkeypatch, tmp_path: Path) -> None:
    module = _release_truth_module()
    report = ROOT / "reports/PRODUCTION_HARD_PREDICATES.json"
    original = report.read_bytes()
    payload = json.loads(original)
    payload["source_tree_sha256"] = "0" * 64
    report.write_text(json.dumps(payload), encoding="utf-8")
    try:
        registry = module._blockers("1" * 64, str(payload.get("release")))
    finally:
        report.write_bytes(original)
    hard = [
        item
        for item in registry["items"]
        if item["id"] in {p["id"] for p in json.loads(PROFILE.read_text())["predicates"]}
    ]
    assert registry["hard_predicate_report_current"] is False
    assert len(hard) == len(json.loads(PROFILE.read_text())["predicates"])
    assert all(item["state"] == "INTERNAL_BLOCKED" for item in hard)
    assert all(item["evidence_current"] is False for item in hard)


def test_release_truth_current_report_preserves_external_boundary() -> None:
    module = _release_truth_module()
    report = json.loads((ROOT / "reports/PRODUCTION_HARD_PREDICATES.json").read_text())
    registry = module._blockers(str(report["source_tree_sha256"]), str(report["release"]))
    hard_ids = {p["id"] for p in json.loads(PROFILE.read_text())["predicates"]}
    hard = [item for item in registry["items"] if item["id"] in hard_ids]
    assert registry["hard_predicate_report_current"] is True
    assert len(hard) == len(json.loads(PROFILE.read_text())["predicates"])
    assert all(item["software_ready"] is True for item in hard)
    assert all(item["externally_satisfied"] is False for item in hard)
    assert all(item["state"] == "EXTERNAL_REQUIRED" for item in hard)
