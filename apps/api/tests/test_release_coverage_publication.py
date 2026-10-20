"""Poison controls: raw coverage numbers must never become signed release claims."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_raw_and_self_declared_union_cannot_publish_without_github_admission(
    tmp_path: Path,
) -> None:
    script = ROOT / "scripts/publish_release_evidence.py"
    spec = importlib.util.spec_from_file_location("release_evidence_under_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    evidence = tmp_path / "var"
    evidence.mkdir()
    totals = {
        "num_statements": 2,
        "covered_lines": 2,
        "num_branches": 2,
        "covered_branches": 2,
    }
    (evidence / "coverage.json").write_text(json.dumps({"totals": totals}))
    assert module.coverage_projection("a" * 64, "v0.9.7") is None
    (evidence / "coverage-union.json").write_text(json.dumps({"totals": totals}))
    assert module.coverage_projection("a" * 64, "v0.9.7") is None


def test_unbound_release_evidence_bypass_is_not_available() -> None:
    source = (ROOT / "scripts/publish_release_evidence.py").read_text(encoding="utf-8")
    assert "--allow-unbound" not in source
    assert "if bound != digest:" in source


def test_failed_publication_revokes_stale_files(monkeypatch, tmp_path: Path) -> None:
    script = ROOT / "scripts/publish_release_evidence.py"
    spec = importlib.util.spec_from_file_location("release_revocation", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    monkeypatch.setattr(module, "release_tag", lambda root: "v0.9.7")
    monkeypatch.setattr(module, "compute_source_digest", lambda root: "a" * 64)
    monkeypatch.setattr(sys, "argv", ["publish_release_evidence.py"])
    output = tmp_path / "reports/release/v0.9.7"
    output.mkdir(parents=True)
    for name in ("COVERAGE_REPORT.json", "DETERMINISM_GATE.json"):
        (output / name).write_text('{"status":"PASS"}')
    assert module.main() == 1
    assert not (output / "COVERAGE_REPORT.json").exists()
    assert not (output / "DETERMINISM_GATE.json").exists()
