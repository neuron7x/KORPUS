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


def test_targeted_state_tells_a_failure_apart_from_a_run_that_did_not_happen() -> None:
    """Один булевий не сміє нести три світи.

    `targeted_ok` злипав «замало відібрано», «справжні падіння» і «не бігало» в одне
    `False`. Читач бачив хибне й висновував, що тести падають.

    ВИМІРЯНО 06.09.2026 на `723d9bb4`: 48 пропущених, з них 44 через ненастроєний
    PostgreSQL. Канонічний бекенд релізу — PostgreSQL, а число готовності рахується
    з прогону на SQLite, який НЕ МОЖЕ дати нуль пропусків. Критерій не хибний і не
    недосяжний — його міряють там, де предмета нема.

    Різниця має різного адресата: `FAIL` знімає інженер, `NOT_MEASURED` — той, хто
    дає середовище.
    """
    module = _module()

    real = module._targeted_state({"tests": 4229, "failures": 0, "errors": 0, "skipped": 48})
    assert real["state"] == "NOT_MEASURED"
    assert "48" in real["reason"]

    assert (
        module._targeted_state({"tests": 4229, "failures": 0, "errors": 0, "skipped": 0})["state"]
        == "PASS"
    )
    assert (
        module._targeted_state({"tests": 4229, "failures": 1, "errors": 0, "skipped": 0})["state"]
        == "FAIL"
    )
    assert (
        module._targeted_state({"tests": 10, "failures": 0, "errors": 0, "skipped": 0})["state"]
        == "NOT_MEASURED"
    )


def test_a_real_failure_outranks_a_run_that_did_not_happen() -> None:
    """FAIL перебиває NOT_MEASURED — інакше падіння сховалось би за пропуском.

    Без цього плеча прогін із одним падінням І сорока вісьмома пропусками звітував
    би «не міряли», і справжня відмова зникла б у класі невиміряного.
    """
    module = _module()

    both = module._targeted_state({"tests": 4229, "failures": 1, "errors": 0, "skipped": 48})

    assert both["state"] == "FAIL"


def test_targeted_ok_stays_true_only_on_a_complete_run() -> None:
    """Дуал: поведінка споживача не змінена, лише названа."""
    module = _module()

    for payload, expected in (
        ({"tests": 4229, "failures": 0, "errors": 0, "skipped": 0}, True),
        ({"tests": 4229, "failures": 0, "errors": 0, "skipped": 48}, False),
        ({"tests": 4229, "failures": 1, "errors": 0, "skipped": 0}, False),
    ):
        assert (module._targeted_state(payload)["state"] == "PASS") is expected
