"""Знаменник не сміє скорочуватись мовчки — і скорочення не сміє бути UNKNOWN.

Виміряно 02.09.2026: прибрати вісь із `answer-axes.json` і прогнати `check_answer_axes` —
код виходу НУЛЬ. Знаменник 16 → 15, вирок зелений. Це і є тихий шлях до готовності:
прибрати те, що міряють, замість того щоб полагодити те, що міряється.

Тут прибито чотири різні способи це зробити: зникнення члена, заміна члена при тій самій
кількості, чисте скорочення лічильника і запис у `removed` без причини.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "check_release_surface", ROOT / "scripts/check_release_surface.py"
)
assert _spec is not None and _spec.loader is not None
surface = importlib.util.module_from_spec(_spec)
sys.modules["check_release_surface"] = surface
_spec.loader.exec_module(surface)

OBSERVED = {
    "answer_axes": ["boundary_own", "refusal", "subject"],
    "hard_predicates": ["live_postgres_rls"],
    "liveness_gates": ["validate-repository"],
    "lane_validate_targets": ["module-budget", "release-surface"],
    "mutants": 565,
    "budgeted_modules": 589,
    "liveness_poisons": 36,
    "scripts_declaring_selftest": 42,
}


def _declared() -> dict[str, object]:
    return surface.record(dict(OBSERVED), {})


def test_an_unchanged_surface_passes():
    assert surface.evaluate(_declared(), OBSERVED)["status"] == "PASS"


def test_a_vanished_axis_is_named_not_merely_counted():
    fewer = {**OBSERVED, "answer_axes": ["boundary_own", "refusal"]}
    verdict = surface.evaluate(_declared(), fewer)
    assert verdict["status"] == "FAIL"
    assert any("subject" in item for item in verdict["shrunk"]), verdict["shrunk"]


def test_a_swap_that_keeps_the_count_is_still_a_shrinkage():
    """Лічильник тут сліпий: 3 → 3, а властивість, яку боронила зникла вісь, не міряє ніхто."""
    swapped = {**OBSERVED, "answer_axes": ["boundary_own", "refusal", "щось_інше"]}
    verdict = surface.evaluate(_declared(), swapped)
    assert verdict["status"] == "FAIL"
    assert any("subject" in item for item in verdict["shrunk"])


def test_a_counted_dimension_may_not_shrink_silently():
    fewer = {**OBSERVED, "mutants": 564}
    verdict = surface.evaluate(_declared(), fewer)
    assert verdict["status"] == "FAIL"
    assert any("mutants" in item for item in verdict["shrunk"])


def test_a_named_removal_is_allowed_because_it_is_a_decision():
    declared = _declared()
    declared["removed"] = [
        {
            "dimension": "answer_axes",
            "member": "subject",
            "on": "2026-09-02",
            "reason": "вісь замінена на дві точніші, обидві оголошені",
        }
    ]
    fewer = {**OBSERVED, "answer_axes": ["boundary_own", "refusal"]}
    assert surface.evaluate(declared, fewer)["status"] == "PASS"


def test_a_removal_without_a_reason_is_not_a_decision():
    """`removed` мусить лишитись рішенням, а не списком, куди дописують заради зеленого.

    Кожне поле перевіряється ОКРЕМО. Перша версія цього тесту прибирала і `reason`, і
    `on` разом — і мутант, що знімав перевірку `reason`, ВИЖИВ: запис усе одно падав на
    відсутньому `on`. Тест, який рухає два входи, не називає жодного.
    """
    fewer = {**OBSERVED, "answer_axes": ["boundary_own", "refusal"]}

    without_reason = _declared()
    without_reason["removed"] = [
        {"dimension": "answer_axes", "member": "subject", "on": "2026-09-02"}
    ]
    assert surface.evaluate(without_reason, fewer)["status"] == "FAIL", "дата без причини"

    without_date = _declared()
    without_date["removed"] = [
        {"dimension": "answer_axes", "member": "subject", "reason": "просто так"}
    ]
    assert surface.evaluate(without_date, fewer)["status"] == "FAIL", "причина без дати"

    without_either = _declared()
    without_either["removed"] = [{"dimension": "answer_axes", "member": "subject"}]
    assert surface.evaluate(without_either, fewer)["status"] == "FAIL"


def test_growth_passes_and_is_still_reported():
    more = {**OBSERVED, "answer_axes": [*OBSERVED["answer_axes"], "нова"], "mutants": 566}
    verdict = surface.evaluate(_declared(), more)
    assert verdict["status"] == "PASS"
    assert len(verdict["grown"]) == 2, "зростання мусить бути названим, а не мовчазним"


def test_the_declaration_in_the_tree_describes_the_tree():
    """Найдешевший спосіб зробити гейт декоративним — лишити декларацію несвіжою."""
    import json

    declared = json.loads(
        (ROOT / "config/operations/release-surface.json").read_text(encoding="utf-8")
    )
    verdict = surface.evaluate(declared, surface.observe(ROOT))
    assert verdict["status"] == "PASS", verdict["shrunk"]


def test_every_declared_dimension_is_actually_observed():
    """Вимір, оголошений і не спостережуваний, — це знаменник, який ніхто не рахує."""
    observed = surface.observe(ROOT)
    for dimension in (*surface.NAMED, *surface.COUNTED):
        assert dimension in observed, f"{dimension} оголошено, але не спостерігається"
