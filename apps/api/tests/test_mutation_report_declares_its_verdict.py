"""Артефакт, який цитують як доказ, мусить ОГОЛОШУВАТИ свій вирок.

ВИМІРЯНО 02.09.2026. `reports/MUTATION_FULL_CATALOGUE_CURRENT.json` — доказ під
претензією CLM-MUTATION у журналі релізу. Після того, як читач прив'язки навчився
бачити конверт `provenance`, каталог прив'язався ПРАВИЛЬНО і все одно дістав
`UNDECLARED_EVIDENCE`: поля вироку в ньому не було взагалі. Вирок доводилось виводити
з `mutation_score`, тобто тримати знання про предмет у читачі.

Читач, що виводить вирок сам, розходиться з предметом МОВЧКИ, щойно предмет зміниться:
`mutation_score` ділить на мутантів, які ще ЗАСТОСОВУЮТЬСЯ, тож мутант, чий рядок
переформатували, тихо залишає знаменник, і 1.0 лишається на місці при каталозі, що
всихає. Саме тому вирок рахується з `mutation_score_over_catalogue` і з переліків
survived/invalid/errors, а не з одного числа.

Порожній перелік результатів — окремий випадок і НЕ успіх: `all([])` істинне, а нуль
мутантів означає, що каталог не бігав.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "apps/api/src"))

from run_mutation_tests import summarize  # noqa: E402


def _result(identifier: str, status: str) -> dict[str, object]:
    return {"id": identifier, "status": status}


def _verdict(results: list[dict[str, object]]) -> str:
    return str(summarize(results, shard_index=None, shard_count=1)["status"])


def test_a_clean_catalogue_declares_pass() -> None:
    assert _verdict([_result("M01", "KILLED"), _result("M02", "KILLED")]) == "PASS"


def test_a_survivor_declares_fail() -> None:
    assert _verdict([_result("M01", "KILLED"), _result("M02", "SURVIVED")]) == "FAIL"


def test_an_invalid_mutant_declares_fail() -> None:
    """Мутант, що перестав застосовуватись, залишає знаменник `mutation_score`.

    Без цього рядка `mutation_score` лишився б 1.0 при каталозі, що всихає — рівно те,
    що сталося 03.08.2026 з M04, M17, M19 і M25 після переносу рядків лінтером.
    """
    assert _verdict([_result("M01", "KILLED"), _result("M02", "INVALID")]) == "FAIL"


def test_an_errored_mutant_declares_fail() -> None:
    assert _verdict([_result("M01", "KILLED"), _result("M02", "ERROR")]) == "FAIL"


def test_an_empty_catalogue_is_not_success() -> None:
    """`all([])` істинне. Нуль мутантів означає, що каталог не бігав, а не що він чистий."""
    assert _verdict([]) == "FAIL"


def test_the_shipped_catalogue_declares_a_verdict() -> None:
    """Негативний контроль до всього файла: поле мусить бути В АРТЕФАКТІ, не лише у функції.

    Перевірки вище звіряють `summarize`. Але претензію підпирає ФАЙЛ, і якщо запис на
    диск колись перестане нести це поле, кожне твердження вище лишиться зеленим.
    """
    import json

    report = json.loads((ROOT / "reports/MUTATION_REPORT.json").read_text(encoding="utf-8"))
    assert "status" in report, "звіт на диску не оголошує вироку"
    assert report["status"] in {"PASS", "FAIL"}
