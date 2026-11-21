"""The release publisher must call live admission; saved numbers remain powerless."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def test_publisher_has_a_positive_live_admission_path(monkeypatch, tmp_path: Path) -> None:
    expected = {
        "schema": "korpus.coverage-report.v1",
        "status": "PASS",
        "source_tree_sha256": "a" * 64,
        "release": "v0.9.7",
        "statement_coverage_percent": 100.0,
        "branch_coverage_percent": 100.0,
    }
    calls: list[tuple[Path, tuple[str, str]]] = []

    def admitted(root: Path, identity: tuple[str, str]) -> dict:
        calls.append((root, identity))
        return expected

    monkeypatch.setitem(
        sys.modules,
        "github_evidence_publication",
        SimpleNamespace(admitted_coverage_projection=admitted),
    )
    script = Path(__file__).resolve().parents[3] / "scripts/publish_release_evidence.py"
    spec = importlib.util.spec_from_file_location("live_release_publisher", script)
    assert spec is not None and spec.loader is not None
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    publisher.ROOT = tmp_path
    assert publisher.coverage_projection("a" * 64, "v0.9.7") == expected
    assert calls == [(tmp_path, ("a" * 64, "v0.9.7"))]
