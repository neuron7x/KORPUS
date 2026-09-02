"""Атака на машину, яка каже PASS. Продукт доведений; сам верифікатор — ні.

568 убитих мутантів — сильний сигнал ПРО ПРОДУКТ. Він нічого не каже про код, який
вирішує, що 568/568 означає готовність. Тут перевіряється саме той код, і перші дві
проби знайшли справжні отвори.

ВИМІРЯНО 02.09.2026 на верифікаторі, який до того вважався надійним:

    {"killed": 0, "mutants": 0, "survived": []}   ->  НУЛЬ проблем
    {}                                            ->  НУЛЬ проблем

Причина в обох одна: `killed != mutants` хибне і для `0 != 0`, і для `None != None`.
Прогін, що не мутував нічого, і звіт, у якому нічого немає, читались як доказ. Це
`NOT_EXECUTED -> PASS` у чистому вигляді — рівно те, що ця система забороняє скрізь,
крім місця, де сама виносить вирок.

Гейт свіжості цього НЕ ловить: звіт, що перелічує всі ідентифікатори каталогу й не
вбиває жодного, для нього свіжий.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "verify_branch_consolidation", ROOT / "scripts/verify_branch_consolidation.py"
)
assert _spec is not None and _spec.loader is not None
verifier = importlib.util.module_from_spec(_spec)
sys.modules["verify_branch_consolidation"] = verifier
_spec.loader.exec_module(verifier)


def test_a_run_that_mutated_nothing_is_not_proof():
    """Найтихіша підміна: нуль на нуль дорівнює, отже «все вбито»."""
    problems = verifier.mutation_consistency({"killed": 0, "mutants": 0, "survived": []})
    assert problems, "звіт із нулем мутантів прочитано як доказ"


def test_an_empty_report_is_not_proof():
    """`None != None` теж хибне — і порожній звіт проходив із тієї самої причини."""
    assert verifier.mutation_consistency({})


@pytest.mark.parametrize(
    "report",
    [
        {"killed": 567, "mutants": 568, "survived": ["M1"]},
        {"killed": 999, "mutants": 568, "survived": []},
        {"killed": None, "mutants": 568, "survived": []},
        {"killed": "568", "mutants": "568", "survived": []},
        {"killed": 568, "mutants": -1, "survived": []},
    ],
    ids=["вижилі", "killed більше", "killed відсутній", "рядки замість чисел", "відʼємні"],
)
def test_every_inconsistent_shape_is_refused(report):
    assert verifier.mutation_consistency(report)


def test_a_report_that_claims_a_full_kill_and_lists_a_survivor_is_refused():
    """Ізолює саме гілку `survived`, а не арифметику поруч.

    У всіх інших випадках із вижилими спрацьовує ще й `killed != mutants`, тож мутант,
    що знімав перевірку `survived`, ВИЖИВАВ: його ловив сусід. Тут арифметика сходиться
    (568/568) і суперечність несе лише перелік вижилих.
    """
    problems = verifier.mutation_consistency({"killed": 568, "mutants": 568, "survived": ["M042"]})
    assert problems and any("M042" in item for item in problems), problems


def test_a_complete_run_is_accepted():
    """Верифікатор, що відхиляє все, не є верифікатором."""
    assert verifier.mutation_consistency({"killed": 568, "mutants": 568, "survived": []}) == []


def test_unknown_and_problem_leave_by_different_exit_codes():
    """`unknown` і `problems` — різні вироки, і код виходу мусить їх розрізняти.

    Один код на обидва зробив би «не виміряно» і «виміряно й зламано» однаковими для
    будь-кого, хто читає лише `$?` — а це рівно те, як їх читає CI.
    """
    source = (ROOT / "scripts/verify_branch_consolidation.py").read_text(encoding="utf-8")
    assert 'if report["problems"]:\n        return 1' in source
    assert 'return 0 if not report["unknown"] else 2' in source


def test_the_verdict_is_not_accepted_while_anything_is_unresolved():
    """ACCEPTED мусить вимагати ОБИДВОХ порожніх списків, не одного."""
    source = (ROOT / "scripts/verify_branch_consolidation.py").read_text(encoding="utf-8")
    assert '"ACCEPTED": not problems and not unknown,' in source
