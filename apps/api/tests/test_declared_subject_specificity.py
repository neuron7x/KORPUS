"""Довжина збігу мусить дожити від розпізнавання предмета до ранжування.

`subjects_in_question` упорядковує предмети від довшого до коротшого, бо «Командир» є
підрядком «Безпосередні командири». Цей порядок губився при перетворенні на множину, і
клас предмета ставав бінарним: усі троє змагалися релевантністю, де узагальнення виграє.

Тут перевіряється саме ланка передачі — те, що ранжувальник ОТРИМУЄ число, а не
членство. Без цього тесту мутація, яка ставить одиницю замість довжини, виживає: ранг
лишається правильним для одного збігу й ламається рівно там, де збігів кілька.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.declared_subject import declared_subject_documents  # noqa: E402


def _candidate(title: str) -> SimpleNamespace:
    return SimpleNamespace(document=SimpleNamespace(id=uuid4(), canonical_title=title))


def test_the_ranker_receives_the_length_of_the_match() -> None:
    specific = _candidate("Обов'язки: Безпосередні командири (Статут, ст.104)")
    generic = _candidate("Обов'язки: Командир (начальник) (Статут, ст.36)")

    found = declared_subject_documents(
        "Які обов'язки має Безпосередні командири?", [specific, generic]
    )

    assert found[str(specific.document.id)] > found[str(generic.document.id)]


def test_membership_still_works_for_callers_that_only_ask_whether() -> None:
    """Допуск доказів питає «чи оголошує предмет», не «наскільки». Він не сміє зламатись."""
    candidate = _candidate("Обов'язки: Днювальний парку (Статут, ст.358)")

    found = declared_subject_documents("Які обов'язки має Днювальний парку?", [candidate])

    assert str(candidate.document.id) in found


def test_a_document_the_question_does_not_name_is_absent() -> None:
    """Негативний контроль: відображення, у яке потрапляють усі, нічого не впорядковує."""
    other = _candidate("Обов'язки: Черговий роти (Статут, ст.312)")

    assert declared_subject_documents("Які обов'язки має Днювальний парку?", [other]) == {}
