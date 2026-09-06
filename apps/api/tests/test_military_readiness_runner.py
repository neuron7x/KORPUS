from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _runner():
    path = ROOT / "scripts/run_military_readiness_campaign.py"
    spec = importlib.util.spec_from_file_location("military_readiness_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_regression_batches_cover_every_test_module_once() -> None:
    module = _runner()
    batches = module.regression_batches(8)
    observed = [item for _, command in batches for item in command[4:]]
    expected = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "apps/api/tests").glob("test_*.py"), key=lambda path: path.name)
    ]
    assert observed == expected
    assert len(observed) == len(set(observed))


def test_regression_batch_size_is_fail_closed() -> None:
    module = _runner()
    try:
        module.regression_batches(0)
    except ValueError:
        pass
    else:
        raise AssertionError("zero batch size must be rejected")


def test_aggregate_status_preserves_fail_and_unknown() -> None:
    module = _runner()
    assert module.aggregate_status([{"status": "PASS"}]) == "PASS"
    assert module.aggregate_status([{"status": "PASS"}, {"status": "UNKNOWN"}]) == "UNKNOWN"
    assert module.aggregate_status([{"status": "UNKNOWN"}, {"status": "FAIL"}]) == "FAIL"


def test_a_campaign_that_never_ran_regression_cannot_report_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Невиконане не є пройденим — а тут воно так рахувалось.

    Регресія живе ОКРЕМИМ полем звіту, і `status` кампанії її не бачив: в обмеженому
    обсязі вона `NOT_EXECUTED`, а `main()` віддавала 0. Прогін, у якому регресію не
    запускали ЖОДНОГО разу, був невідрізненний від прогону, де вона пройшла. Виміряно
    незалежною сесією 06.09.2026.
    """
    module = _runner()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "run_one", lambda *a, **k: {"status": "PASS", "name": "x"})
    monkeypatch.setattr(module, "regression_batches", lambda *a, **k: [])
    monkeypatch.setattr(module, "BASELINE", [("baseline", ["true"])])
    monkeypatch.setattr(sys, "argv", ["run_military_readiness_campaign.py", "--output", "out.json"])

    assert module.main() == 1, "кампанія звітувала PASS про набір, якого не виконувала"
    report = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert report["regression"]["status"] == "NOT_EXECUTED"
    assert "NOT_EXECUTED" in capsys.readouterr().err


def test_a_campaign_whose_regression_passed_is_not_punished_for_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Дуал: без нього попередній тест задовольняє кампанія, яка ЗАВЖДИ віддає 1."""
    module = _runner()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "run_one", lambda *a, **k: {"status": "PASS", "name": "x"})
    monkeypatch.setattr(module, "regression_batches", lambda *a, **k: [("b", ["cmd"])])
    monkeypatch.setattr(module, "BASELINE", [("baseline", ["true"])])
    monkeypatch.setattr(module, "run_parallel", lambda *a, **k: [{"status": "PASS", "name": "b"}])
    monkeypatch.setattr(
        sys, "argv", ["run_military_readiness_campaign.py", "--full", "--output", "out.json"]
    )

    assert module.main() == 0
    report = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert report["regression"]["status"] == "PASS"
