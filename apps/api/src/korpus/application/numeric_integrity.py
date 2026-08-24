"""Damage to the numbers, which is where extraction damage actually matters.

`assess_extraction_quality` reads the text as a stream of characters: replacement
characters, control bytes, alphanumeric density, runaway tokens. Every one of those
flags fires on text that is visibly broken. None of them fires on the failure that
changes what an order says.

"не менше 300 м" arriving as "не менше 3 00 м" is clean by every existing predicate:
the alphanumeric ratio is fine, there are no replacement characters, no control bytes,
no long tokens. The passage is quotable, the citation resolves, and the answer states
a distance two orders of magnitude wrong. Same for a Cyrillic З read as a 3, for "1,5"
becoming "1.5" in a document that otherwise writes decimal commas, and for a unit that
ends up on the far side of a line break from its quantity.

What this module can and cannot do is worth stating exactly, because the honest limit
is narrow. Without the source bytes, no code here can prove a number was lost — a
document that genuinely says 300 and a document whose 3000 lost a zero are the same
string. What is detectable is *internal inconsistency*: forms that no publisher writes
and no correct extraction produces. So these are suspicion flags for a reviewer, the
same contract `ExtractionQuality` already has, and they are deliberately not folded
into a confidence score. A score would let a reviewer skip the passage; a flag names
which passage to open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from korpus.application.printed_numbers import parse_printed_decimal as _to_decimal

# A quantity: digits, optional decimal separator, optional unit. Units are listed
# rather than pattern-matched because "м" is also a word fragment; requiring a word
# boundary and a known unit keeps the false-positive rate at something a reviewer will
# still read.
UNITS = (
    "мм|см|дм|м|км|мг|г|кг|т|мл|л|год|хв|сек|с|доб|діб|дні|днів|%|°C|°С|шт|осіб|грн"
    "|mm|cm|km|kg|ml|km/h|m"
)
QUANTITY = re.compile(rf"(?<![\w,.])(\d[\d\s.,]*)\s*({UNITS})(?![\w])", re.IGNORECASE)

# "3 00" — a space inside a number where the group that follows is not three digits, so
# it cannot be a thousands separator. "1 500" is ordinary; "3 00" and "1 5" are not.
SPLIT_NUMBER = re.compile(r"\b\d{1,3}(?: \d{1,2}\b)(?! ?\d)")

# Digits and letters that share a glyph. The Cyrillic pair is the one that matters for
# a Ukrainian corpus: З/3, О/0, б/6 survive OCR looking like text.
DIGIT_LETTER = re.compile(
    # between digits — 1О5
    r"(?<=\d)[OoОоЗзlI|бБ](?=\d)"
    # leading — З00
    r"|\b[ЗзOoОо](?=\d)"
    # trailing, but only where a unit follows: "5б кг" is a damaged 56, while a bare
    # "5б" is an ordinary sub-unit designation in Ukrainian military text and flagging
    # it would put the flag on passages that are perfectly fine.
    rf"|(?<=\d)[OoОоЗзlI|бБ](?=\s*(?:{UNITS})\b)"
)

DECIMAL_COMMA = re.compile(r"\d,\d")
DECIMAL_POINT = re.compile(r"\d\.\d(?!\d*\.)")

# A quantity whose unit was pushed onto the next line. The number is still right, but a
# span boundary drawn between them cites a bare figure with no dimension.
DETACHED_UNIT = re.compile(rf"\d\s*\n\s*({UNITS})(?![\w])", re.IGNORECASE)

RANGE = re.compile(r"від\s+(\d[\d\s.,]*)\s*(?:до|-|—)\s*(\d[\d\s.,]*)", re.IGNORECASE)

SPLIT_NUMBER_FLAG = "split_number"
DIGIT_LETTER_FLAG = "digit_letter_confusion"
MIXED_DECIMAL_FLAG = "mixed_decimal_separators"
DETACHED_UNIT_FLAG = "detached_unit"
INVERTED_RANGE_FLAG = "inverted_range"


@dataclass(frozen=True)
class NumericIntegrity:
    quantities: int
    flags: frozenset[str]
    samples: tuple[str, ...]

    @property
    def suspect(self) -> bool:
        return bool(self.flags)


def assess_numeric_integrity(text: str) -> NumericIntegrity:
    """Deterministic suspicion flags over the quantities in an extracted passage."""

    flags: set[str] = set()
    samples: list[str] = []

    quantities = QUANTITY.findall(text)

    for match in SPLIT_NUMBER.finditer(text):
        flags.add(SPLIT_NUMBER_FLAG)
        samples.append(match.group(0))

    if DIGIT_LETTER.search(text):
        flags.add(DIGIT_LETTER_FLAG)
        samples.extend(match.group(0) for match in DIGIT_LETTER.finditer(text))

    # Both separators in one passage means at least one of them is not what the
    # publisher wrote, and which one decides whether 1.500 is one and a half or fifteen
    # hundred.
    if DECIMAL_COMMA.search(text) and DECIMAL_POINT.search(text):
        flags.add(MIXED_DECIMAL_FLAG)

    for match in DETACHED_UNIT.finditer(text):
        flags.add(DETACHED_UNIT_FLAG)
        samples.append(" ".join(match.group(0).split()))

    for low_raw, high_raw in RANGE.findall(text):
        low, high = _to_decimal(low_raw), _to_decimal(high_raw)
        if low is not None and high is not None and low > high:
            flags.add(INVERTED_RANGE_FLAG)
            samples.append(f"від {low_raw.strip()} до {high_raw.strip()}")

    return NumericIntegrity(
        quantities=len(quantities),
        flags=frozenset(flags),
        # Bounded: a passage with two hundred damaged figures needs a reviewer, not a
        # two-hundred-entry list, and an unbounded sample would put corpus text into
        # every report that carries this record.
        samples=tuple(samples[:8]),
    )
