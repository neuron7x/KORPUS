"""Перевірка свіжості доказів мусить розрізняти дві РІЗНІ причини несвіжості.

Виробник застаріває від зміни джерела, споживач — від перевипуску будь-якого виробника.
Злиття їх в одну перевірку дало б вирок «щось не так», який не називає команди, а саме
за назвою команди ця перевірка й існує: 02.09.2026 три різні гейти сказали одну причину
трьома словами, і три прогони пішли на те, щоб це зрозуміти.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "check_evidence_freshness", ROOT / "scripts/check_evidence_freshness.py"
)
assert _spec is not None and _spec.loader is not None
freshness = importlib.util.module_from_spec(_spec)
sys.modules["check_evidence_freshness"] = freshness
_spec.loader.exec_module(freshness)


def _producer(path: Path, digest: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"provenance": {"source_digest": digest}}), encoding="utf-8")


def _tree(root: Path, digest: str) -> None:
    for relative, _ in freshness.PRODUCERS:
        _producer(root / relative, digest)
    consumer, _, inputs = freshness.CONSUMERS[0]
    hashes = {
        name: hashlib.sha256((root / source).read_bytes()).hexdigest()
        for name, source in inputs.items()
    }
    (root / consumer).write_text(json.dumps({"evidence_sha256": hashes}), encoding="utf-8")


def test_a_producer_that_measured_another_tree_is_named_with_its_target(tmp_path, monkeypatch):
    _tree(tmp_path, "a" * 64)
    monkeypatch.setattr(freshness, "compute_source_digest", lambda _root: "a" * 64)
    assert freshness.evaluate(tmp_path)["status"] == "PASS"

    monkeypatch.setattr(freshness, "compute_source_digest", lambda _root: "b" * 64)
    verdict = freshness.evaluate(tmp_path)
    assert verdict["status"] == "FAIL"
    stale = [row for row in verdict["reports"] if row["state"] == "ПРО ІНШЕ ДЕРЕВО"]
    assert len(stale) == len(freshness.PRODUCERS)
    assert "mutation" in verdict["rerun_in_this_order"]


def test_a_consumer_is_stale_when_an_input_moved_even_though_the_tree_did_not(
    tmp_path, monkeypatch
):
    """Друга причина, невидима першій: джерело те саме, вхід споживача — інший."""
    _tree(tmp_path, "a" * 64)
    monkeypatch.setattr(freshness, "compute_source_digest", lambda _root: "a" * 64)
    assert freshness.evaluate(tmp_path)["status"] == "PASS"

    # той самий дайджест дерева, інші байти в одному вході
    _producer(tmp_path / "var/scale-report.json", "a" * 64)
    (tmp_path / "var/scale-report.json").write_text(
        json.dumps({"provenance": {"source_digest": "a" * 64}, "note": "перевипущено"}),
        encoding="utf-8",
    )
    verdict = freshness.evaluate(tmp_path)
    assert verdict["status"] == "FAIL"
    consumer = next(row for row in verdict["reports"] if row["role"] == "споживач")
    assert consumer["state"] == "СУДИВ ІНШІ ФАЙЛИ"
    assert consumer["moved_inputs"] == ["scale"]
    assert verdict["rerun_in_this_order"] == ["operational-gate"]


def test_a_report_without_provenance_is_not_read_as_fresh(tmp_path, monkeypatch):
    """UNKNOWN не є PASS: звіт, що не каже про яке дерево він, не свіжий."""
    _tree(tmp_path, "a" * 64)
    monkeypatch.setattr(freshness, "compute_source_digest", lambda _root: "a" * 64)
    (tmp_path / "var/eval-report.json").write_text("{}", encoding="utf-8")
    verdict = freshness.evaluate(tmp_path)
    assert verdict["status"] == "FAIL"
    row = next(r for r in verdict["reports"] if r["report"] == "var/eval-report.json")
    assert row["state"] == "БЕЗ ПОХОДЖЕННЯ"


@pytest.mark.parametrize("broken", ["{не json", ""])
def test_unreadable_evidence_fails_closed_rather_than_raising(tmp_path, monkeypatch, broken):
    _tree(tmp_path, "a" * 64)
    monkeypatch.setattr(freshness, "compute_source_digest", lambda _root: "a" * 64)
    (tmp_path / "var/migration-report.json").write_text(broken, encoding="utf-8")
    assert freshness.evaluate(tmp_path)["status"] == "FAIL"


def test_the_selftest_carries_its_own_negative_control():
    assert freshness.selftest() == 0
