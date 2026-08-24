from __future__ import annotations

import json
from pathlib import Path

import scripts.run_local_production_preflight as preflight
from korpus.application.provenance import compute_source_digest
from scripts.coverage_gap_plan import build_plan
from scripts.release_identity import release_tag

ROOT = Path(__file__).resolve().parents[3]


def _coverage(branch_percent: float, statement_percent: float, branches: int = 1000) -> dict:
    statements = 1000
    covered_branches = round(branch_percent * branches)
    covered_lines = round(statement_percent * statements)
    return {
        "totals": {
            "num_statements": statements,
            "covered_lines": covered_lines,
            "num_branches": branches,
            "covered_branches": covered_branches,
            "missing_branches": branches - covered_branches,
        },
        "files": {},
    }


def test_coverage_ratchet_refuses_pre_v050_branch_floor(tmp_path: Path) -> None:
    policy = json.loads((ROOT / "config/operations/test-adaptation-policy.json").read_text())
    report = build_plan(_coverage(0.899, 0.96), policy, tmp_path)
    assert report["status"] == "FAIL"
    assert report["minimum_branch_rate"] == 0.90
    assert report["minimum_statement_rate"] == 0.95


def test_coverage_ratchet_accepts_only_when_both_floors_hold(tmp_path: Path) -> None:
    policy = json.loads((ROOT / "config/operations/test-adaptation-policy.json").read_text())
    report = build_plan(_coverage(0.91, 0.96), policy, tmp_path)
    assert report["status"] == "PASS"
    assert report["source_tree_sha256"] == compute_source_digest(tmp_path)
    assert report["release"] == release_tag()



def test_coverage_ratchet_refuses_growth_in_uncovered_branch_edges(tmp_path: Path) -> None:
    policy = json.loads((ROOT / "config/operations/test-adaptation-policy.json").read_text())
    # 250 missing edges exceeds the current ratcheted ceiling even though rates pass.
    report = build_plan(_coverage(0.91, 0.96, branches=2778), policy, tmp_path)
    assert report["branch_rate"] >= 0.90
    assert report["remaining_missing_branches"] > report["missing_branch_ceiling"]
    assert report["status"] == "FAIL"

def _seed_preflight_reports(root: Path, *, digest: str | None) -> None:
    policy = root / "config/operations/reference-v5.json"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(json.dumps({"assurance": {"minimum_line_rate": 0.95, "minimum_branch_rate": 0.90}}), encoding="utf-8")
    if digest is None:
        digest = compute_source_digest(root)
    report_dir = root / "reports/release/v0.5.0"
    report_dir.mkdir(parents=True)
    for name, filename in preflight.REPORT_NAMES.items():
        payload: dict[str, object] = {
            "status": "PASS",
            "release": "v0.5.0",
            "source_tree_sha256": digest,
        }
        if name == "backend":
            payload.update({"failed": 0, "errors": 0})
        if name == "coverage":
            payload.update(
                {"statement_coverage_percent": 95.1, "branch_coverage_percent": 90.1}
            )
        (report_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def test_preflight_rejects_stale_green_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(preflight, "release_tag", lambda _root=None: "v0.5.0")
    _seed_preflight_reports(tmp_path, digest="0" * 64)
    report = preflight.evaluate(tmp_path, which=lambda _tool: "/bin/true")
    assert report["status"] == "FAIL_LOCAL"
    assert not any(report["local_checks"].values())
    assert report["production_authorized"] is False


def test_preflight_accepts_current_local_evidence_but_never_self_authorizes(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(preflight, "release_tag", lambda _root=None: "v0.5.0")
    _seed_preflight_reports(tmp_path, digest=None)
    report = preflight.evaluate(tmp_path, which=lambda _tool: "/bin/true")
    assert report["status"] == "PASS_WITH_EXTERNAL_BLOCKERS"
    assert all(report["local_checks"].values())
    assert report["production_authorized"] is False


def test_ci_and_canonical_cycle_enforce_adaptive_gates() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for target in ("coverage-ratchet", "determinism-gate", "stress-gate"):
        assert f"$(MAKE) {target}" in makefile or target in makefile
        assert f"make {target}" in ci
    assert "release-mutation-delta" in makefile
