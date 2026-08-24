from __future__ import annotations

import json
from pathlib import Path

from korpus.application.provenance import compute_source_digest

from scripts.run_local_production_preflight import REPORT_NAMES, evaluate

RELEASE = "v0.5.0"


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "tree"
    (root / "apps/api/src/korpus").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "apps/api/src/korpus/release.json").write_text(
        '{"schema":"korpus.release-identity.v1","product":"KORPUS","version":"0.5.0",'
        '"tag":"v0.5.0","artifact_stem":"KORPUS_SYSTEM_v0.5.0"}\n',
        encoding="utf-8",
    )
    policy = root / "config/operations/reference-v5.json"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        json.dumps({"assurance": {"minimum_line_rate": 0.95, "minimum_branch_rate": 0.90}}),
        encoding="utf-8",
    )
    digest = compute_source_digest(root)
    report_dir = root / "reports/release" / RELEASE
    report_dir.mkdir(parents=True)
    for name, filename in REPORT_NAMES.items():
        payload: dict[str, object] = {
            "status": "PASS",
            "release": RELEASE,
            "source_tree_sha256": digest,
        }
        if name == "backend":
            payload.update({"failed": 0, "errors": 0})
        if name == "coverage":
            payload.update({"statement_coverage_percent": 95.0, "branch_coverage_percent": 90.0})
        (report_dir / filename).write_text(json.dumps(payload), encoding="utf-8")
    return root


def test_local_success_never_claims_production_authorization(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(
        "scripts.run_local_production_preflight.release_tag", lambda _root=None: RELEASE
    )
    report = evaluate(root, which=lambda _tool: "/usr/bin/tool")
    assert report["status"] == "PASS_WITH_EXTERNAL_BLOCKERS"
    assert report["production_authorized"] is False
    assert "EXTERNAL_INDEPENDENT_REDTEAM_REQUIRED" in report["external_blockers"]


def test_missing_local_evidence_fails_closed(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    (root / "reports/release" / RELEASE / REPORT_NAMES["backend"]).unlink()
    monkeypatch.setattr(
        "scripts.run_local_production_preflight.release_tag", lambda _root=None: RELEASE
    )
    assert evaluate(root, which=lambda _tool: None)["status"] == "FAIL_LOCAL"


def test_missing_scanner_is_visible_blocker(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(
        "scripts.run_local_production_preflight.release_tag", lambda _root=None: RELEASE
    )
    report = evaluate(root, which=lambda tool: None if tool == "trivy" else "/usr/bin/tool")
    assert "CONTAINER_OS_SCANNER_UNAVAILABLE" in report["external_blockers"]


def test_stale_green_report_is_rejected(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    path = root / "reports/release" / RELEASE / REPORT_NAMES["coverage"]
    payload = json.loads(path.read_text())
    payload["source_tree_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "scripts.run_local_production_preflight.release_tag", lambda _root=None: RELEASE
    )
    report = evaluate(root, which=lambda _tool: "/usr/bin/tool")
    assert report["status"] == "FAIL_LOCAL"
    assert report["local_checks"]["coverage"] is False
