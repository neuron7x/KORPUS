"""Locale-aware parsing of printed quantities, including everything it refuses.

Ukrainian and Russian normative texts print thousands with a space or a dot and the
fraction with a comma; English sources do the opposite. When both separators appear the
last one is the decimal point, which resolves the string exactly.

When only one appears the string is genuinely ambiguous — `1.500` is fifteen hundred in a
Ukrainian order and one-and-a-half in an English one — and the parser takes a single
separator as decimal. That choice is what these tests pin down: not because it is the only
defensible reading, but because it is the one the system makes, and a silent change of it
would move every quantity in the corpus by three orders of magnitude.

Measured on 2026-08-28 the module sat at 66.7% branch coverage with every rejection path
untaken.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from korpus.application.printed_numbers import parse_printed_decimal


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1500", "1500"),
        ("1 500", "1500"),
        ("1\u00a0500", "1500"),
        ("1\u202f500", "1500"),
        ("123", "123"),
        ("0,5", "0.5"),
        ("1,500.25", "1500.25"),
        ("1.500,25", "1500.25"),
        ("12,345,678.90", "12345678.90"),
        ("12.345.678,90", "12345678.90"),
    ],
)
def test_printed_quantities_parse_to_the_number_a_reader_would_say(
    raw: str, expected: str
) -> None:
    """With both separators present the reading is unambiguous: the last one is decimal."""
    assert parse_printed_decimal(raw) == Decimal(expected)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1.500", "1.500"), ("1,500", "1.500"), ("1.5", "1.5"), ("1,5", "1.5")],
)
def test_a_single_separator_is_read_as_a_decimal_point(raw: str, expected: str) -> None:
    """The ambiguous case, pinned. A Ukrainian `1.500` meaning 1500 reads as 1.5 here."""
    assert parse_printed_decimal(raw) == Decimal(expected)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("12.345.678", "12345678"), ("12 345 678", "12345678"), ("1.500.000", "1500000")],
)
def test_repeated_separators_are_read_as_thousands_grouping(raw: str, expected: str) -> None:
    """More than one separator cannot be a decimal point, so grouping is the only reading."""
    assert parse_printed_decimal(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["", "   ", "abc", "-5", "+5", ".5", ",5", "\u22125"])
def test_a_value_that_does_not_start_with_a_digit_is_refused(raw: str) -> None:
    """A leading sign or separator is not a printed quantity in these sources.

    Refusing is the point: guessing which reading was meant would put a number in a
    citation nobody printed.
    """
    assert parse_printed_decimal(raw) is None


@pytest.mark.parametrize(
    "raw",
    ["12.34.5", "1.500.00", "1234.567.890", "1.500,", "1.500,2a", "1,500.ab", "12..34"],
)
def test_a_grouping_that_is_not_three_digits_is_refused(raw: str) -> None:
    """Groups of four, two or none are not thousands separators; the string is unreadable.

    Taking a best guess here is exactly how a quantity moves by a factor of a thousand
    without anything in the pipeline noticing.
    """
    assert parse_printed_decimal(raw) is None


def test_a_leading_group_longer_than_three_digits_is_refused_when_grouping(
) -> None:
    """The first group may be one to three digits; beyond that it is not grouping."""
    assert parse_printed_decimal("1234.567.890") is None
    assert parse_printed_decimal("123.456.789") == Decimal("123456789")
