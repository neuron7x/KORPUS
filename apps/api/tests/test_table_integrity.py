"""A row that lost a column quotes one heading's value under another.

Norms live in tables, and PDF extraction has no notion of a cell. When a row loses a
column the remaining figures shift left, and the flattened text is still grammatical:
the citation resolves to real bytes and the answer states a norm that does not exist.
Neither the character-level quality predicates nor `numeric_integrity` can see it — a
correct number in the wrong column is a correct number.

Paired throughout, and the negative half is the harder one. A detector that fires on
wrapped prose or on a single line with several figures would be worse than nothing:
the flag would appear on most passages and stop being read.
"""

from __future__ import annotations

from korpus.application.table_integrity import (
    TABLE_STRUCTURE_LOST,
    assess_table_integrity,
)

INTACT = (
    "Норма витрат\n"
    "Категорія    Добова норма    Одиниця\n"
    "Перша        2,5             кг\n"
    "Друга        1,8             кг\n"
    "Третя        1,2             кг\n"
)

RAGGED = (
    "Норма витрат\n"
    "Категорія    Добова норма    Одиниця\n"
    "Перша        2,5             кг\n"
    "Друга        1,8\n"
    "Третя        1,2             кг\n"
)


def test_a_table_that_kept_its_shape_is_not_flagged() -> None:
    """The dual, and the one that decides whether the flag is worth reading."""
    result = assess_table_integrity(INTACT)

    assert result.flags == frozenset()
    assert result.blocks == 1
    assert result.ragged_blocks == 0


def test_a_row_that_lost_a_column_is_flagged() -> None:
    """"Друга 1,8" — the unit is gone, and nothing downstream can tell which one."""
    result = assess_table_integrity(RAGGED)

    assert TABLE_STRUCTURE_LOST in result.flags
    assert result.ragged_blocks == 1
    assert any("Друга" in sample for sample in result.samples)


def test_ordinary_prose_is_not_a_table() -> None:
    text = (
        "Встановити зону безпеки не менше 300 м від об'єкта. "
        "Доповісти про виконання до 18:00 5 серпня 2026 року."
    )

    assert assess_table_integrity(text).flags == frozenset()


def test_wrapped_prose_with_single_spaces_is_not_a_table() -> None:
    """Single spaces are word gaps; only an aligned run survives as a column boundary."""
    text = "\n".join(
        [
            "Норма добових витрат становить 2,5 кг на особу",
            "для першої категорії та 1,8 кг для другої",
            "категорії згідно з додатком 3 до наказу",
        ]
    )

    assert assess_table_integrity(text).flags == frozenset()


def test_two_rows_are_not_enough_to_judge_a_shape() -> None:
    """Below three rows there is no established shape to be inconsistent with."""
    text = "Перша        2,5    кг\nДруга        1,8\n"

    result = assess_table_integrity(text)

    assert result.blocks == 0
    assert result.flags == frozenset()


def test_a_line_with_several_numbers_is_not_a_row_without_column_gaps() -> None:
    text = "Витрати 2,5 1,8 1,2 кг на добу відповідно до категорій\n" * 4

    assert assess_table_integrity(text).flags == frozenset()


def test_a_block_of_text_rows_without_digits_is_not_a_table() -> None:
    """A three-column layout of words is a layout; the norms case always carries figures."""
    text = "\n".join(["Перша     колонка     тексту"] * 4)

    assert assess_table_integrity(text).flags == frozenset()


def test_two_tables_separated_by_prose_are_judged_separately() -> None:
    """A paragraph between them must not join two intact tables into one ragged block."""
    first = "Перша        2,5    кг\nДруга        1,8    кг\nТретя        1,2    кг\n"
    second = "Літо        10    год\nЗима        14    год\nМіжсезоння  12    год\n"
    text = f"{first}\nЗастосовується з дати затвердження.\n\n{second}"

    result = assess_table_integrity(text)

    assert result.blocks == 2
    assert result.flags == frozenset()


def test_samples_are_bounded() -> None:
    """This record travels into gate artefacts; it must not become a corpus extract."""
    block = "\n".join(f"Рядок{index}    {index},5    кг" for index in range(30))
    text = block + "\nОстанній    9,9\n"

    result = assess_table_integrity(text)

    assert TABLE_STRUCTURE_LOST in result.flags
    assert len(result.samples) <= 6


def test_table_damage_reaches_the_reviewer_through_the_extraction_quality_gate() -> None:
    """Same contract as the numeric flags: it blocks approval until acknowledged."""
    from korpus.application.extraction_quality import assess_extraction_quality

    assert TABLE_STRUCTURE_LOST in assess_extraction_quality(RAGGED).flags
    assert TABLE_STRUCTURE_LOST not in assess_extraction_quality(INTACT).flags
