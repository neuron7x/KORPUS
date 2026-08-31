"""Дві назви однієї системи — один предмет, а не два.

Виміряно 31.08.2026 на корпусі, який обслуговується: п'ятнадцять названих систем
існують ЛИШЕ латиницею. «Страйкер» не знаходив 335 прольотів про Stryker, «джавелін» —
113 про Javelin. Відмова приходила як факт про корпус, і корпус її не спростовував.
"""

from __future__ import annotations

import json
from pathlib import Path

from korpus.application.answer_analysis import sentence_candidates
from korpus.application.retrieval_math import (
    candidate_terms,
    fold_aliases,
    transliteration_aliases,
)

ROOT = Path(__file__).resolve().parents[3]


def test_the_query_reaches_the_latin_form() -> None:
    terms = dict(candidate_terms("Що таке Джавелін?"))

    assert "javelin" in terms, "латинська форма не потрапила в пошуковий запит"


def test_the_document_side_folds_to_what_was_asked() -> None:
    """Розширюється ДОКУМЕНТ, не питання — і це виміряне рішення, не смак.

    Перша редакція додавала латинську форму до токенів ПИТАННЯ й тим піднімала
    знаменник покриття: «Як застосовується Хаймарс?» ставало трьома токенами, з яких у
    прольоті може бути лише один, тобто стеля падала до 0.33 при порозі 0.5. Питання
    про транслітеровану систему ставало важчим саме через ліки: «Джавелін» (два токени)
    полагодилось, «Хаймарс» і «Шахед» (три) — ні.
    """
    assert fold_aliases({"himars", "battery"}) == {"хаймарс", "battery"}


def test_coverage_counts_the_pair_as_one_class() -> None:
    """Знаменник лишається тим, що спитали: синонім не робить питання дорожчим."""
    covered = sentence_candidates("HIMARS battery fires", frozenset({"хаймарс"}))

    assert covered[0].query_coverage == 1.0


def test_a_word_outside_the_table_is_untouched() -> None:
    """Негативний контроль: згортання звужене до виміряних записів."""
    assert fold_aliases({"наказ", "варта"}) == {"наказ", "варта"}


def test_every_entry_is_measured_not_imagined() -> None:
    """Таблиця — дані, і кожен запис несе число, яким його можна переміряти."""
    table = json.loads((ROOT / "config/corpus/transliteration.json").read_text("utf-8"))

    assert table["entries"], "порожня таблиця не є таблицею"
    for entry in table["entries"]:
        assert entry["latin_spans"] > 0, f"{entry['ua']}: запис без виміряних прольотів"
        assert entry["ua_spans"] == 0, f"{entry['ua']}: українська форма вже резолвиться"
    assert len(transliteration_aliases()) == len(table["entries"])
