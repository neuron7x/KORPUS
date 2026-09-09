"""Клас середовища і його ПІДСТАВА не сміють суперечити одне одному в одному звіті.

Виміряно 09.09.2026: звіт проби ніс `environment_class: LOCAL_DEV` поруч із підставою
«оголошені юніти активні, несуть поточний код і є предметом виміру». Обидва рядки були
правдиві про РІЗНІ предмети — клас про рішення (прапорець може лише послабити), підстава
про вимір, — і разом читались як пряме протиріччя, яке нічим не розвʼязати.

Правило прапорця перевіряється тут же: угору він не піднімає НІКОЛИ. Інакше
`--environment-class PRODUCTION` на дев-машині робив би прогін доказом про продакшен.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("load_probe", ROOT / "scripts/load_probe.py")
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)

MEASURED_STRONG = {"environment_class": "PRODUCTION_LIKE", "basis": "юніти обслуговують"}
MEASURED_WEAK = {"environment_class": "LOCAL_DEV", "basis": "процеси, старші за код"}


def _decide(measured: dict[str, Any], requested: str) -> tuple[str, str]:
    """Кличе САМУ функцію, а не її копію.

    Перша редакція цього тесту повторювала правило власним кодом — і тоді він зеленів би
    навіть тоді, коли `load_probe.py` розійдеться з ним: два оголошення одного правила
    розходяться мовчки. Тепер предмет один.
    """
    return PROBE.decide_environment_class(measured, requested)


def test_the_flag_never_raises_the_class() -> None:
    """Найдорожче правило: попросити продакшен на дев-машині не робить його продакшеном."""
    assert _decide(MEASURED_WEAK, "PRODUCTION")[0] == "LOCAL_DEV"
    assert _decide(MEASURED_WEAK, "PRODUCTION_LIKE")[0] == "LOCAL_DEV"


def test_the_flag_may_lower_the_class() -> None:
    assert _decide(MEASURED_STRONG, "CI_FIXTURE")[0] == "CI_FIXTURE"


def test_a_lowered_class_says_so_instead_of_borrowing_the_measurement_basis() -> None:
    """Підстава мусить пояснювати ЗАПИСАНИЙ клас, а не той, що був виміряний."""
    environment_class, basis = _decide(MEASURED_STRONG, "LOCAL_DEV")
    assert environment_class == "LOCAL_DEV"
    assert "послабив" in basis
    assert "юніти обслуговують" in basis


def test_an_unlowered_class_keeps_the_measurement_basis() -> None:
    environment_class, basis = _decide(MEASURED_STRONG, "PRODUCTION_LIKE")
    assert environment_class == "PRODUCTION_LIKE"
    assert basis == "юніти обслуговують"


def test_the_lane_can_ask_for_the_class_at_all() -> None:
    """Без цього предикат `production_like_load` недосяжний через `make`: дефолт
    LOCAL_DEV перемагав би вимір, скільки б разів пробу не ганяли."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile[makefile.index("\nload-probe:") : makefile.index("\nload-probe:") + 600]
    assert "--environment-class" in recipe
    assert "ENVIRONMENT_CLASS" in recipe
