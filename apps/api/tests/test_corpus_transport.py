"""Корпус мусить ПЕРЕНОСИТИСЬ. Без цього закритої бети не буває.

256 документів живуть лише в ігнорованому `var/`, тож свіжий клон дає систему з одним
фікстурним документом — і саме її побачить запрошена людина. Незалежний аудит
06.09.2026 виніс «дороги дістати корпус НЕМАЄ»; дорога існувала й працює, невидимим
було її ІМʼЯ: ціль описувала захист від втрати, а не встановлення.

Тести тримають вирок, а не механізм: механізм доводиться прогоном
(`reports/closure/CORPUS_TRANSPORT_REHEARSAL.json`), вирок — тут.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "verify_corpus_transport", ROOT / "scripts/verify_corpus_transport.py"
)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)

FULL = {"documents": 256, "approved_versions": 256, "spans": 31464, "objects": 256, "h": "a"}
EMPTY = {"documents": 0, "approved_versions": 0, "spans": 0, "objects": 0, "h": "a"}
GOOD = {
    "objects_checked": 256,
    "bytes_hashed": 42751494,
    "content_addressing_holds": True,
    "mismatches": [],
}


def test_an_identical_non_empty_restore_passes() -> None:
    assert GATE.verdict(FULL, FULL, GOOD)["status"] == "PASS"


def test_a_restore_that_lost_spans_fails_and_names_the_axis() -> None:
    result = GATE.verdict(FULL, {**FULL, "spans": 1}, GOOD)
    assert result["status"] == "FAIL"
    assert result["differences"] == {"spans": [31464, 1]}


def test_an_empty_corpus_carried_faithfully_is_not_a_transported_corpus() -> None:
    """Порожнеча, перенесена тотожно, задовольняє «однакові» й доводить нуль.

    Це той самий знаменник, що ловить `guard-asks-not-zero-instead-of-enough`: гейт
    мусить питати «чи достатньо», а не «чи збігається».
    """
    assert GATE.verdict(EMPTY, EMPTY, GOOD)["status"] == "FAIL"


def test_object_bytes_that_did_not_survive_fail_the_verdict() -> None:
    torn = {**GOOD, "content_addressing_holds": False, "mismatches": [{"name": "x", "actual": "y"}]}
    assert GATE.verdict(FULL, FULL, torn)["status"] == "FAIL"


def test_zero_objects_hashed_is_not_a_clean_content_check() -> None:
    """Вирок не сміє довіряти прапорцю, якого сам не перевіряв.

    Нуль перехешованих обʼєктів і чиста перевірка виглядають однаково, якщо читати
    лише `content_addressing_holds`. Спіймано власною самоперевіркою цього ж гейта.
    """
    assert GATE.verdict(FULL, FULL, {**GOOD, "objects_checked": 0})["status"] == "FAIL"


def test_mismatches_alone_fail_even_when_the_flag_says_otherwise() -> None:
    """Дуал попереднього: прапорець бреше в ОБИДВА боки, і вирок мусить пережити обидва."""
    lying = {**GOOD, "mismatches": [{"name": "x", "actual": "y"}]}
    assert GATE.verdict(FULL, FULL, lying)["status"] == "FAIL"


def test_the_survey_does_not_count_one_thing_twice() -> None:
    """Множина імен обʼєктів і множина `source_hash` тотожні ЗА ПОБУДОВОЮ.

    Перша редакція звіту рахувала обидві й видавала за дві осі — два різні поля з
    однаковим значенням. Незалежна вісь одна: чи дійшли БАЙТИ.
    """
    import inspect

    source = inspect.getsource(GATE.survey)
    assert "object_name_set" not in source, "вісь, тотожна сусідній за побудовою, повернулась"
