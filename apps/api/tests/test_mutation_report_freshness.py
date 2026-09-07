"""Звіт мутацій, що описує інший каталог, виглядає точно як свіжий.

Двічі за 31.08.2026 `reports/MUTATION_REPORT.json` розійшовся з кодом (379 проти 385,
потім 385 проти 390), і обидва рази це пережило зелений `make validate`: число
«убито 100 %» лишалось на місці й читалось як доказ про набір правил, якого в дереві
вже не було.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from check_mutation_report_freshness import problems  # noqa: E402

EXPECTED = {"M01", "M02", "M03"}
#: Еталон мусить мати форму СПРАВЖНЬОГО звіту, інакше він перевіряє інший предмет.
#: Було: `results` без поля `status` і `source_digest` із шістдесяти чотирьох нулів —
#: тобто рівно та отрута, яку selftest самого скрипта оголошував чистим випадком
#: (виправлено 06.09.2026), і рівно та форма, якої реальний
#: `reports/MUTATION_REPORT.json` не має: там усі 624 рядки несуть `status: KILLED`.
#: Через відсутній `status` перевірка «підсумок мусить збігатися з результатами»
#: читала три рядки як невбитих і валила ПОЗИТИВНИЙ випадок.
GOOD: dict = {
    "mutants": 3,
    "results": [
        {"id": "M01", "status": "KILLED"},
        {"id": "M02", "status": "KILLED"},
        {"id": "M03", "status": "KILLED"},
    ],
    "killed": 3,
    "provenance": {"source_digest": "a" * 64},
    "survived": [],
    "invalid": [],
    "errors": [],
}


def test_a_report_that_matches_the_catalogue_passes() -> None:
    """Негативний контроль до всього нижчого: гейт, що відхиляє все, — не гейт."""
    assert problems(GOOD, EXPECTED) == []


def test_a_mutant_the_report_never_saw_is_caught() -> None:
    """Тест мусить падати З ТІЄЇ ПРИЧИНИ, яку охороняє.

    Доти він питав лише «чи список зауважень непорожній». Коли 06.09.2026 у гейт
    додали перевірку «підсумок мусить збігатися з результатами», вона почала
    спрацьовувати РАНІШЕ — і мутант `M354_FRESHNESS_GATE_IGNORES_A_MISSING_MUTANT`
    (`missing = sorted(expected - reported)` -> `missing = []`) ВИЖИВ: тест
    червонів з іншої причини й більше не доводив нічого про `missing`.
    Тепер він називає своє зауваження, а `killed` вирівняно, щоб сусідня перевірка
    мовчала і не рятувала мутанта.
    """
    stale = {**GOOD, "results": GOOD["results"][:2], "mutants": 2, "killed": 2}

    found = problems(stale, EXPECTED)

    assert any("яких звіт не бачив" in problem for problem in found), found


def test_an_exchange_that_keeps_the_count_is_caught() -> None:
    """Один прибрано, інший додано — лічильник не ворухнеться.

    Тому порівнюється МНОЖИНА ідентифікаторів, а не кількість.
    """
    swapped = {**GOOD, "results": [{"id": "M01"}, {"id": "M02"}, {"id": "M99"}]}

    assert problems(swapped, EXPECTED)


def test_a_report_without_provenance_is_refused() -> None:
    """Непідв'язаний PASS гірший за відсутній: він виглядає як доказ."""
    unbound = {key: value for key, value in GOOD.items() if key != "provenance"}

    assert problems(unbound, EXPECTED)


def test_a_report_of_a_failing_run_is_not_evidence() -> None:
    assert problems({**GOOD, "survived": ["M02"]}, EXPECTED)


def test_the_two_names_of_one_report_never_diverge() -> None:
    """`MUTATION_REPORT.json` і `MUTATION_FULL_CATALOGUE_CURRENT.json` — один доказ.

    Прогін оновлював лише друге, а перше — те, яке читає цей самий гейт свіжості, —
    переносили рукою. Тому після кожної зміни каталогу `validate` червонів на свіжості
    звіту, і причина була не в каталозі, а в тому, що одну річ оновлювали двома
    дорогами. Тепер обидва пишуться з одного рядка; розбіжність означає, що хтось
    правив копію окремо.
    """
    first = (ROOT / "reports/MUTATION_REPORT.json").read_bytes()
    second = (ROOT / "reports/MUTATION_FULL_CATALOGUE_CURRENT.json").read_bytes()
    assert first == second, "два імені одного звіту розійшлися — одне з них редагували окремо"


def test_a_summary_that_disagrees_with_its_own_results_is_caught() -> None:
    """Окремий тест на окрему властивість — інакше вони рятують мутантів одне одного."""
    lying = {**GOOD, "killed": 99}

    found = problems(lying, EXPECTED)

    assert any("оголошує killed=99" in problem for problem in found), found


def test_results_that_are_not_all_killed_are_caught() -> None:
    """Звіт, де підсумкові списки порожні, а самі результати кажуть інше."""
    survived_quietly = {
        **GOOD,
        "results": [{"id": "M01", "status": "SURVIVED"}, *GOOD["results"][1:]],
        "killed": 3,
    }

    found = problems(survived_quietly, EXPECTED)

    assert any("невбитих мутантів" in problem for problem in found), found
