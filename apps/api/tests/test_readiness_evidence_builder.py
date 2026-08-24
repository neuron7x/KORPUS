from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "build_readiness_947_evidence.py"


def _module():
    spec = importlib.util.spec_from_file_location("readiness_evidence_builder_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_report_requires_exact_source_and_release(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "status": "PASS",
                "source_tree_sha256": "a" * 64,
                "release": "v0.8.0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    assert module._report_pass("report.json", source_digest="a" * 64, release="v0.8.0")
    assert not module._report_pass("report.json", source_digest="b" * 64, release="v0.8.0")
    assert not module._report_pass("report.json", source_digest="a" * 64, release="v0.9.0")


def test_missing_report_never_becomes_pass(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    assert not module._report_pass("missing.json", source_digest="a" * 64, release="v0.8.0")


def test_historical_migration_carry_requires_baseline_binding() -> None:
    module = _module()
    report = {
        "migration": "head",
        "table_set_match": True,
        "column_failures": {},
        "audit_head_seeded": True,
        "sqlite_fts5_present": True,
        "provenance": {"source_digest": "a" * 64},
    }
    assert module._migration_carry_ok(report, "a" * 64)
    assert not module._migration_carry_ok(report, "b" * 64)


def test_local_load_carry_requires_complete_successful_phases_and_binding() -> None:
    module = _module()
    phase = {"requests": 3, "statuses": {"200": 3}}
    report = {
        "source_tree_sha256": "a" * 64,
        "release": "v0.6.1",
        "environment_class": "LOCAL_DEV",
        "load": phase,
        "spike": phase,
        "soak": phase,
        "drift_p50_seconds": 0.01,
    }
    assert module._local_load_carry_ok(report, "a" * 64)
    report["spike"] = {"requests": 3, "statuses": {"200": 2, "503": 1}}
    assert not module._local_load_carry_ok(report, "a" * 64)


def test_dimension_fails_closed_when_any_criterion_is_false() -> None:
    module = _module()
    result = module._dimension(
        criteria={"executed": True, "source_bound": False},
        evidence_class="EXECUTED",
        source_digest="a" * 64,
        release="v0.9.7",
    )
    assert result["status"] == "FAIL"
    assert result["failures"] == ["source_bound"]


def test_dimension_pass_requires_nonempty_all_true_criteria() -> None:
    module = _module()
    passed = module._dimension(
        criteria={"executed": True, "source_bound": True},
        evidence_class="EXECUTED",
        source_digest="a" * 64,
        release="v0.9.7",
    )
    empty = module._dimension(
        criteria={},
        evidence_class="EXECUTED",
        source_digest="a" * 64,
        release="v0.9.7",
    )
    assert passed["status"] == "PASS"
    assert passed["failures"] == []
    assert empty["status"] == "FAIL"
