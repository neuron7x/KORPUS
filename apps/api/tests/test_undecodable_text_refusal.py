"""Text a PDF font produced but no encoder can write is refused where it is read.

Found by importing 1616 real documents. A PDF with a broken font encoding decodes to
lone surrogates — Python holds them in a `str`, `str.encode` will not. They travelled the
whole pipeline and died at `EvidenceSpanRecord`, so the import reported thirteen
documents refused with a Pydantic message about "unable to parse raw data as a unicode
string": the wrong thing named, at the wrong layer, after extraction and chunking had
already been paid for.

Refused, not stripped. Removing the undecodable characters leaves a passage that reads
as the document's own words while no longer being them, and the single promise this
system makes about a citation is that the quote is what the source says.

The negative control is the last test: ordinary text — including the double space this
module deliberately preserves — must still pass. A guard that refuses everything makes
the first test pass and the corpus empty.
"""

from __future__ import annotations

import pytest
from korpus.infrastructure.extraction import _normalize

#: What a broken CMap yields: a high surrogate with no low one. Valid `str`, invalid
#: UTF-8, and invisible until something tries to write it.
LONE_SURROGATE = "\ud83d"


def test_a_lone_surrogate_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="not valid Unicode"):
        _normalize(f"на деревьях {LONE_SURROGATE} б")


def test_the_refusal_names_the_text_not_the_record() -> None:
    """The message a curator reads must point at the document, not at a schema."""
    with pytest.raises(ValueError) as raised:
        _normalize(LONE_SURROGATE)

    message = str(raised.value)
    assert "EvidenceSpanRecord" not in message, message
    assert "document text" in message, message


def test_the_undecodable_text_is_not_silently_repaired() -> None:
    """Stripping would produce a quote the source does not contain."""
    with pytest.raises(ValueError):
        _normalize(f"перше{LONE_SURROGATE}друге")


@pytest.mark.parametrize(
    "text",
    [
        "звичайний текст",
        "текст  з подвійним пробілом",
        "колонка\tколонка",
        "емодзі 🛡 і кирилиця",
        "",
    ],
)
def test_valid_text_still_passes(text: str) -> None:
    """The negative control. A guard that refuses everything passes every test above."""
    _normalize(text)
