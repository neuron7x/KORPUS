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
GOOD: dict = {
    "mutants": 3,
    "results": [{"id": "M01"}, {"id": "M02"}, {"id": "M03"}],
    "provenance": {"source_digest": "0" * 64},
    "survived": [],
    "invalid": [],
    "errors": [],
}


def test_a_report_that_matches_the_catalogue_passes() -> None:
    """Негативний контроль до всього нижчого: гейт, що відхиляє все, — не гейт."""
    assert problems(GOOD, EXPECTED) == []


def test_a_mutant_the_report_never_saw_is_caught() -> None:
    stale = {**GOOD, "results": GOOD["results"][:2], "mutants": 2}

    assert problems(stale, EXPECTED)


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
