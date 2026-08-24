"""A table flattened into prose still reads as a sentence, and says something else.

Norms in military documents live in tables: consumption per day, distances by
category, times by condition. PDF text extraction returns a stream of lines with no
notion of a cell, so a table survives as whitespace — and the failure mode is not that
it looks broken. It is that a row loses a column and the remaining figures shift left,
so a value from one column is quoted under another column's heading. The passage is
grammatical, the citation resolves to real bytes, and the answer states a norm that
does not exist.

`assess_extraction_quality` cannot see this: the alphanumeric ratio is fine, there are
no replacement characters, and `numeric_integrity` reads each figure in isolation — a
correct number in the wrong column is a correct number.

What is detectable without the source is inconsistency between the rows of one block.
A table has a shape: consecutive lines carrying several whitespace-separated columns.
When those lines disagree about how many columns they have, one of them lost or gained
a cell, and no reader of the flattened text can tell which. That is the flag.

The limits are worth stating, because a detector that fires on ordinary prose is worse
than none. A single line with several numbers is not a table. Prose wrapped to a
column width is not a table. And a genuinely ragged source table — one with merged
cells — will be flagged despite being extracted correctly, which is the right way
round: a merged cell is exactly where a flattened quotation goes wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TABLE_STRUCTURE_LOST = "table_structure_lost"

# Two or more spaces are what survives of a column boundary in flattened PDF text. A
# single space is a word gap, and a tab is already an explicit boundary.
COLUMN_GAP = re.compile(r"(?: {2,}|\t+)")
DIGIT = re.compile(r"\d")

#: A block shorter than this is not enough evidence of a table to judge its shape.
MINIMUM_ROWS = 3
#: Membership in a block. Two aligned columns is enough to belong, because the row that
#: *lost* a column is the one being looked for: requiring three to belong made the
#: damaged row break the block instead of making it ragged, which is exactly backwards
#: and is how the first version of this module reported every damaged table as clean.
MINIMUM_COLUMNS = 2
#: A block only counts as a table if some row still shows three columns. Two-column
#: pairs are a definition list, not a table with a norm in the third cell.
TABLE_WIDTH = 3


@dataclass(frozen=True)
class TableIntegrity:
    candidate_rows: int
    blocks: int
    ragged_blocks: int
    flags: frozenset[str]
    samples: tuple[str, ...]

    @property
    def suspect(self) -> bool:
        return bool(self.flags)


def _columns(line: str) -> list[str]:
    return [cell for cell in COLUMN_GAP.split(line.strip()) if cell]


def _is_candidate_row(line: str) -> bool:
    """A line that looks like a table row: several columns, at least one numeric.

    The numeric requirement is what keeps ordinary formatted prose out. A norms table
    without a single figure in it is not the case this protects; a heading row with no
    digits still joins a block through the rows beneath it.
    """
    columns = _columns(line)
    return len(columns) >= MINIMUM_COLUMNS and any(DIGIT.search(cell) for cell in columns)


def assess_table_integrity(text: str) -> TableIntegrity:
    """Flag blocks of table-like rows that disagree about their own column count."""

    lines = text.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if _is_candidate_row(line):
            current.append(line)
            continue
        if len(current) >= MINIMUM_ROWS:
            blocks.append(current)
        current = []
    if len(current) >= MINIMUM_ROWS:
        blocks.append(current)

    tables = [
        block
        for block in blocks
        if max(len(_columns(line)) for line in block) >= TABLE_WIDTH
    ]
    ragged: list[list[str]] = []
    for block in tables:
        widths = {len(_columns(line)) for line in block}
        if len(widths) > 1:
            ragged.append(block)

    flags: set[str] = set()
    samples: list[str] = []
    if ragged:
        flags.add(TABLE_STRUCTURE_LOST)
        for block in ragged[:2]:
            for line in block[:3]:
                samples.append(" ".join(line.split()))

    return TableIntegrity(
        candidate_rows=sum(len(block) for block in tables),
        blocks=len(tables),
        ragged_blocks=len(ragged),
        flags=frozenset(flags),
        # Bounded for the same reason the numeric samples are: this record travels into
        # gate artefacts and must not become a corpus extract.
        samples=tuple(samples[:6]),
    )
