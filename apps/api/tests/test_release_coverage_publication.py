"""Poison controls: raw coverage numbers must never become signed release claims."""

from __future__ import annotations

import importlib.util
import json
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
