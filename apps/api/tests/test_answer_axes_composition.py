"""Профіль без композиції — це дашборд: він показує і нічого не забороняє.

Шість осей відповіді міряються окремо з 31.08.2026, і жодна не була вироком над рештою.
Доктрину взято з десятиосьового гейта GeoSync, де вона коштувала п'яти адверсарних
раундів і 31 дефекту: вердикт = НАЙСЛАБША вісь, UNMEASURED ніколи не кладеться в
підлогу, і сліпу пробу не можна заморозити як пройдену.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from check_answer_axes import compose, measure_axis  # noqa: E402


def _axis(name: str, value: float, floor: float) -> dict[str, Any]:
    return {
        "axis": name,
        "state": "MEASURED",
        "value": value,
        "floor": floor,
        "population": 10,
        "below_floor": value < floor,
    }


BLIND = {"axis": "сліпа", "state": "UNMEASURED", "reason": "немає звіту"}


def test_the_verdict_is_the_weakest_axis_not_the_mean() -> None:
    """Одна провалена вісь серед п'яти відмінних — середнє сказало б «добре»."""
    result = compose([_axis("a", 0.99, 0.8), _axis("b", 0.99, 0.8), _axis("c", 0.10, 0.8)], [])

    assert result["verdict"] == "FAIL"
    assert result["weakest"] is None or result["weakest"]["axis"] == "c"


def test_all_axes_inside_their_floors_pass() -> None:
    """Негативний контроль: гейт, що відхиляє все, не є гейтом."""
    assert compose([_axis("a", 0.9, 0.8), _axis("b", 0.85, 0.8)], [])["verdict"] == "PASS"


def test_a_blind_axis_is_not_a_passed_axis() -> None:
    """UNMEASURED не є PASS. Сліпа вісь могла б виявитись найслабшою, а найслабша і є
    вироком — тому вирок стає невизначеним, а не зеленим."""
    result = compose([_axis("a", 0.99, 0.8), BLIND], [])

    assert result["verdict"] == "UNKNOWN"
    assert "сліпа" in result["unmeasured"]


def test_a_known_failed_axis_outranks_a_blind_axis() -> None:
    result = compose([_axis("failed", 0.1, 0.8), BLIND], [])

    assert result["verdict"] == "FAIL"
    assert result["weakest"]["axis"] == "failed"
    assert "сліпа" in result["unmeasured"]


def test_the_weakest_axis_is_named_not_just_counted() -> None:
    """Вирок без імені осі не дає що робити далі."""
    weakest = compose([_axis("a", 0.99, 0.8), _axis("b", 0.42, 0.1)], [])["weakest"]

    assert weakest is not None
    assert weakest["axis"] == "b"


def test_a_relaxed_floor_without_a_reason_is_refused() -> None:
    """Підлога, зсунута мовчки, не відрізняється від підлоги, якої ніколи не було."""
    assert compose([_axis("a", 0.9, 0.8)], [{"axis": "a", "reason": "-"}])["verdict"] == "FAIL"


def test_a_missing_report_is_unmeasured_not_zero(tmp_path: Path) -> None:
    """Відсутній звіт — це «не міряли», а не «виміряли нуль».

    Нуль читається як виміряна підлога і тягне вирок у FAIL з хибної причини; UNMEASURED
    каже правду: судити нема чого.
    """
    axis = measure_axis("x", {"report": "var/absent.json", "field": "v", "floor": 0.5}, tmp_path)

    assert axis["state"] == "UNMEASURED"
    assert "value" not in axis


def test_a_report_that_says_it_failed_to_measure_is_not_credited(tmp_path: Path) -> None:
    """Транспортна відмова, зарахована як вимір, — це та сама хибна підлога."""
    (tmp_path / "var").mkdir()
    (tmp_path / "var/unknown.json").write_text('{"status": "UNKNOWN", "v": 0.99}', encoding="utf-8")

    axis = measure_axis("x", {"report": "var/unknown.json", "field": "v", "floor": 0.5}, tmp_path)

    assert axis["state"] == "UNMEASURED"


def test_an_inverted_axis_counts_the_right_direction(tmp_path: Path) -> None:
    """«Скільки чужих питань впускає» — менше краще, тож вісь інвертується.

    Без інверсії ця вісь винагороджувала б рівно те, що мала карати.
    """
    (tmp_path / "var").mkdir()
    (tmp_path / "var/b.json").write_text('{"out": {"rate": 0.2}}', encoding="utf-8")

    axis = measure_axis(
        "foreign",
        {"report": "var/b.json", "path": ["out", "rate"], "invert": True, "floor": 0.7},
        tmp_path,
    )

    assert axis["value"] == 0.8
