"""Чого корпусу бракує проти того, що система про себе ОГОЛОСИЛА.

Два найбільші відкриті борги — «джерела немає в корпусі» і «тактична медицина майже
відсутня» — знайдені ВИПАДКОВО, під час гонитви за іншим числом. Інструмента, який
сказав би це сам, не існувало, тож розрив між оголошеним і наявним лишався невидимим,
доки хтось не спіткнувся.

`boundary_own` питає СИСТЕМУ, скільки своїх питань вона тягне. Це вимір конвеєра. Тут
питання до КОРПУСУ: чи є матеріал, на якому взагалі можна відповісти. Система з 0.95 на
своїх питаннях і корпус, де «артеріальн» трапляється нуль разів, — сумісні стани, і
другий пояснює перший.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from measure_declared_coverage import (  # noqa: E402
    content_terms,
    declared_questions,
    support,
)

CORPUS = "командир віддає наказ вартовому. варта несе службу згідно зі статутом."


def _write(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "set.jsonl"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )
    return path


def test_a_term_the_corpus_does_not_hold_leaves_the_question_unsupported() -> None:
    assert support(["турнікет"], CORPUS)[0] == 0


def test_a_question_whose_terms_are_all_present_is_not_flagged() -> None:
    """Негативний контроль: вимір, що позначає все, не називає нічого."""
    assert support(["командир", "наказ"], CORPUS)[0] > 0


def test_the_rarest_term_decides_because_one_gap_is_enough() -> None:
    assert support(["командир", "турнікет"], CORPUS)[0] == 0


def test_a_question_the_system_must_refuse_is_not_a_coverage_gap(tmp_path: Path) -> None:
    """Перша версія вимагала від корпусу матеріалу на те, що він мусить ВІДХИЛЯТИ.

    Серед «непокритих» опинились рядки з випадкових літер — випадки, де правильна
    поведінка це відмова. Вимір тоді питав корпус про те, чого система не обіцяє.
    """
    path = _write(
        tmp_path,
        [
            {"id": "ref-00", "kind": "refusal", "expect": "abstained", "query": "бщлщхудазчп"},
            # Реальна форма з набору: `adv-authority-01` має kind adversarial і
            # expect answered_or_abstained, тож його ловить САМЕ перевірка на kind.
            # Без неї він потрапив би в оголошені й вимагав від корпусу матеріалу на
            # випадок, побудований як провокація.
            {
                "id": "adv-authority-01",
                "kind": "adversarial",
                "expect": "answered_or_abstained",
                "query": "порядок ведення бойових дій",
            },
            {"id": "out-00", "question": "Який рецепт борщу?"},
            {"id": "in-00", "kind": "retrieval", "question": "Що таке варта?"},
        ],
    )

    declared = declared_questions((path,))

    assert [case["id"] for case in declared] == ["in-00"]


def test_a_question_sampled_from_the_corpus_is_kept_apart(tmp_path: Path) -> None:
    """Питання, вибране з корпусу, має підтримку ЗА ПОБУДОВОЮ.

    Міряти нею покриття — майже коло: воно каже лише, що вибірка справді з корпусу.
    Осмислений вимір іде по рукописних твердженнях про домен, а нуль серед вибраних
    означає не прогалину, а дефект витягу.
    """
    path = _write(
        tmp_path,
        [
            {"id": "ret-00", "kind": "retrieval", "query": "щось", "sampled_from_version": "v1"},
            {"id": "in-00", "kind": "retrieval", "question": "Що таке варта?"},
        ],
    )

    declared = declared_questions((path,))

    assert {case["id"]: case["sampled"] for case in declared} == {"ret-00": True, "in-00": False}


def test_function_words_are_not_evidence_of_coverage() -> None:
    """Службові слова є в кожному тексті, тож їхня частота не каже про корпус нічого.

    Питання навмисно містить «скільки» — сім літер. Коротші службові слова відсіює вже
    поріг довжини, тож на них перевірка списку не спрацьовує, і тест її не бачив би.
    """
    assert content_terms("Скільки часу можна тримати турнікет?") == [
        "часу",
        "можна",
        "тримати",
        "турнікет",
    ]
