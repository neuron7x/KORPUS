"""Хто перевіряє перевіряльника.

`verify_selftest_coverage.py` виключає САМ СЕБЕ зі свого знаменника — запустити власний
`--selftest` усередині себе означало б рекурсію. Виняток законний, але лишав гарантію
неповною рівно на один скрипт, і покривався ОДНИМ рядком рецепта `selftest-coverage`.

Прибери той рядок — і `--selftest` цього гейта не бігатиме НІДЕ, мовчки, а звіт і далі
казатиме «жодної пропущеної»: виключений зі знаменника не з'явиться серед пропущених.
Саме тому наявність рядка стала перевіркою, а не домовленістю.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "selftest_coverage", ROOT / "scripts/verify_selftest_coverage.py"
)
assert _SPEC and _SPEC.loader
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)


def test_the_checker_is_covered_on_this_tree():
    assert gate._self_is_covered(ROOT)["verdict"] == "PASS"


def test_the_checker_notices_its_own_line_is_gone(tmp_path: Path):
    """Негативний контроль: рецепт без рядка мусить дати FAIL, а не мовчання."""
    (tmp_path / "Makefile").write_text("selftest-coverage:\n\t@true\n", encoding="utf-8")
    finding = gate._self_is_covered(tmp_path)
    assert finding["verdict"] == "FAIL"
    assert "НІХТО не запускає" in finding["detail"]


def test_the_gate_excludes_exactly_itself_and_nothing_else():
    declared = gate.declaring(ROOT)
    assert gate.SELF in declared, "гейт мусить бачити себе серед тих, хто оголошує --selftest"
    assert len([s for s in declared if s == gate.SELF]) == 1
