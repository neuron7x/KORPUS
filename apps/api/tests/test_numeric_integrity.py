"""The extraction failure that leaves the text looking perfect.

Every existing extraction-quality predicate fires on visibly broken text. The failure
that changes what an order *says* leaves the text clean: "не менше 300 м" arriving as
"не менше 3 00 м" has a fine alphanumeric ratio, no replacement characters, no control
bytes and no long tokens. It is quotable, the citation resolves, and the answer is
wrong by two orders of magnitude.

The tests are paired: for each damage form, one passage that must be flagged and one
ordinary passage that must not be. A detector that fires on "1 500 м" would be worse
than none — a reviewer who sees the flag on every second passage stops reading it.
"""

from __future__ import annotations

import pytest
from korpus.application.numeric_integrity import (
    DETACHED_UNIT_FLAG,
    DIGIT_LETTER_FLAG,
    INVERTED_RANGE_FLAG,
    MIXED_DECIMAL_FLAG,
    SPLIT_NUMBER_FLAG,
    assess_numeric_integrity,
)


def test_an_ordinary_passage_carries_no_suspicion() -> None:
    """The dual, and the harder half: a detector that always fires is not read."""
    text = (
        "Встановити зону безпеки не менше 300 м від об'єкта. "
        "Резерв — 1 500 л пального та 2,5 т вантажу на добу."
    )

    result = assess_numeric_integrity(text)

    assert result.flags == frozenset()
    assert result.quantities >= 3
    assert result.suspect is False


def test_a_number_split_by_a_space_is_flagged() -> None:
    """The failure this module exists for: 300 read as 3 00, and nothing else notices."""
    result = assess_numeric_integrity("Встановити зону безпеки не менше 3 00 м від об'єкта.")

    assert SPLIT_NUMBER_FLAG in result.flags
    assert "3 00" in result.samples


def test_a_thousands_separator_is_not_a_split_number() -> None:
    """Ukrainian typography writes 1 500; flagging it would flag most of the corpus."""
    result = assess_numeric_integrity("Резерв становить 1 500 л та 12 000 кг.")

    assert SPLIT_NUMBER_FLAG not in result.flags


@pytest.mark.parametrize(
    "text",
    [
        "Дистанція З00 м.",  # Cyrillic З for 3
        "Термін 1О діб.",  # Cyrillic О for 0
        "Норма 5б кг.",  # б for 6
    ],
)
def test_a_letter_standing_in_for_a_digit_is_flagged(text: str) -> None:
    """OCR substitutions inside numbers survive every character-level predicate."""
    assert DIGIT_LETTER_FLAG in assess_numeric_integrity(text).flags


def test_ordinary_cyrillic_text_beside_numbers_is_not_flagged() -> None:
    result = assess_numeric_integrity("Озброєння: 40 мм гармата, боєкомплект 300 пострілів.")

    assert DIGIT_LETTER_FLAG not in result.flags


def test_two_decimal_separators_in_one_passage_are_flagged() -> None:
    """Which separator is real decides whether 1.500 is one and a half or fifteen hundred."""
    result = assess_numeric_integrity("Довжина 2,5 м, ширина 1.5 м.")

    assert MIXED_DECIMAL_FLAG in result.flags


def test_one_consistent_decimal_separator_is_not_flagged() -> None:
    assert MIXED_DECIMAL_FLAG not in assess_numeric_integrity("Довжина 2,5 м, ширина 1,5 м.").flags


def test_a_unit_separated_from_its_quantity_by_a_line_break_is_flagged() -> None:
    """A span boundary drawn there cites a bare figure with no dimension."""
    result = assess_numeric_integrity("Відстань не менше 300\nм від межі.")

    assert DETACHED_UNIT_FLAG in result.flags


def test_a_unit_on_the_same_line_is_not_flagged() -> None:
    result = assess_numeric_integrity("Відстань 300 м.\nДалі — резерв.")

    assert DETACHED_UNIT_FLAG not in result.flags


def test_an_inverted_range_is_flagged() -> None:
    """Either the extraction damaged it or the source is wrong; both need a human."""
    result = assess_numeric_integrity("Глибина від 300 до 100 м.")

    assert INVERTED_RANGE_FLAG in result.flags
    assert "від 300 до 100" in result.samples


def test_an_ordinary_range_is_not_flagged() -> None:
    assert INVERTED_RANGE_FLAG not in assess_numeric_integrity("Глибина від 100 до 300 м.").flags


def test_a_decimal_range_is_compared_numerically_not_lexically() -> None:
    """ "9,5" > "10,0" as strings; a lexical comparison would invent an inversion."""
    assert INVERTED_RANGE_FLAG not in assess_numeric_integrity("Від 9,5 до 10,5 год.").flags


def test_european_grouped_decimal_range_preserves_magnitude() -> None:
    result = assess_numeric_integrity("Глибина від 1.234,5 до 900 м.")
    assert INVERTED_RANGE_FLAG in result.flags


def test_us_grouped_decimal_range_preserves_magnitude() -> None:
    result = assess_numeric_integrity("Глибина від 1,234.5 до 900 м.")
    assert INVERTED_RANGE_FLAG in result.flags


def test_grouped_decimal_non_inversion_is_not_invented() -> None:
    assert (
        INVERTED_RANGE_FLAG not in assess_numeric_integrity("Глибина від 900 до 1.234,5 м.").flags
    )


def test_samples_are_bounded_so_a_report_does_not_carry_the_passage() -> None:
    """This record travels into gate artefacts; it must not become a corpus extract."""
    text = " ".join(f"{index} 0{index} м" for index in range(1, 40))

    result = assess_numeric_integrity(text)

    assert SPLIT_NUMBER_FLAG in result.flags
    assert len(result.samples) <= 8


def test_text_without_quantities_is_not_suspicious() -> None:
    result = assess_numeric_integrity("Наказ доводиться до особового складу під підпис.")

    assert result.quantities == 0
    assert result.suspect is False


def test_numeric_damage_reaches_the_reviewer_through_the_extraction_quality_gate() -> None:
    """A detector nothing consults changes no decision.

    `extraction_quality_flags` already blocks a review transition until a reviewer
    acknowledges them (repository.transition_version). Putting the numeric flags in
    that same set means a passage with a split number cannot be approved silently —
    which is the only place the detection is worth anything.
    """
    from korpus.application.extraction_quality import assess_extraction_quality

    damaged = assess_extraction_quality("Встановити зону безпеки не менше 3 00 м від межі.")
    clean = assess_extraction_quality("Встановити зону безпеки не менше 300 м від межі.")

    assert SPLIT_NUMBER_FLAG in damaged.flags
    assert clean.flags == frozenset()


def test_the_combined_flag_set_stays_within_the_column_bound() -> None:
    """DocumentVersionRecord caps the set at 16; eleven predicates now feed it."""
    from korpus.application.extraction_quality import assess_extraction_quality

    worst = assess_extraction_quality(
        "�\x07 3 00\nм " + "!" * 25 + " З00 2,5 1.5 від 300 до 100 м " + "x" * 130
    )

    assert len(worst.flags) <= 16
    assert SPLIT_NUMBER_FLAG in worst.flags
