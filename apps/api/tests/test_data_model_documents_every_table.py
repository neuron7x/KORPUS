"""A table nobody wrote down is a table nobody reviews.

The account layer arrived as six tables at once and the data model named none of them.
Nothing failed: the schema was correct, the migrations ran, the tests passed. What was
missing was the sentence that lets somebody reviewing an access question know the table
exists at all.

Physical names, because that is the thing that drifts. The conceptual paragraphs above the
appendix use `Document` and `Chunk`; a check against those would pass while `messages` went
undescribed for a year.
"""

from __future__ import annotations

import re
from pathlib import Path

from korpus.infrastructure.repository import metadata

DOC = Path(__file__).resolve().parents[3] / "docs/architecture/DATA_MODEL.md"


def _documented() -> set[str]:
    body = DOC.read_text(encoding="utf-8")
    appendix = body.split("## Physical tables", 1)
    assert len(appendix) == 2, "the physical-table appendix is gone"
    return set(re.findall(r"^\| `([a-z_]+)` \|", appendix[1], re.MULTILINE))


def test_every_table_the_system_creates_is_described() -> None:
    undescribed = sorted(set(metadata.tables) - _documented())
    assert not undescribed, (
        f"these tables exist and are described nowhere in the data model: {undescribed}"
    )


def test_nothing_is_described_that_does_not_exist() -> None:
    """The mirror. A row for a table that was renamed is a sentence about nothing."""
    stale = sorted(_documented() - set(metadata.tables))
    assert not stale, f"the data model describes tables that do not exist: {stale}"


def test_the_appendix_is_read_from_the_appendix() -> None:
    """Negative control: the conceptual prose above must not satisfy the check.

    `Document` appears in the first paragraph; if the parser read the whole file, a
    physical table named `documents` could look documented because of a sentence about a
    different thing.
    """
    body = DOC.read_text(encoding="utf-8")
    prose = body.split("## Physical tables", 1)[0]
    assert "documents" in _documented()
    assert not re.findall(r"^\| `([a-z_]+)` \|", prose, re.MULTILINE), (
        "a table row appears above the appendix, so the parser is reading the wrong section"
    )
