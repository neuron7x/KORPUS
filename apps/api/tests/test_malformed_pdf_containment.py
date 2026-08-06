"""One unreadable document must not end a batch.

Found by importing 1740 real documents. `PdfReader(strict=True)` parses the trailer, not
the page tree — pypdf walks the tree lazily, on the first `len(reader.pages)`. That call
sat between two blocks that both convert `PdfReadError` into a `ValueError`, and was
guarded by neither. A library PDF with a duplicated key in a page dictionary therefore
raised `PdfReadError` out of `extract_pages_from_path`, past `import_corpus.py`'s
per-file handler, and ended the run at document 918 of 1740.

The cost was not the lost document. It was that the importer prints its report at the
end, so five hours of work produced a traceback and no record of what had been ingested,
what had been refused, or why.

Tested by making the page tree raise rather than by carrying a corrupt file: a fixture
PDF broken enough to fail is usually broken enough to fail *earlier*, at construction,
where the existing guard already catches it. That test would pass without the fix. The
fake below fails at exactly the statement that broke and nowhere else.

Two rules:

  * every parser failure leaves as a ValueError naming what was wrong,
  * and no single document can end a batch, whatever it raises.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

import pytest
from pypdf.errors import PdfReadError

from korpus.infrastructure import extraction

PDF_BYTES = b"%PDF-1.4\n%%EOF\n"


class _LazilyBrokenPages:
    """A page tree that parses when constructed and fails when walked, like pypdf's."""

    def __len__(self) -> NoReturn:
        raise PdfReadError("Multiple definitions in dictionary at byte 0x1b277 for key /Im44")


class _Reader:
    is_encrypted = False

    def __init__(self, *arguments: Any, **keywords: Any) -> None:
        self.pages = _LazilyBrokenPages()


def _extract(path: Path) -> None:
    extraction.extract_pages_from_path(
        path=path,
        filename=path.name,
        mime_type="application/pdf",
        ocr_enabled=False,
        ocr_languages="ukr",
        max_pdf_pages=500,
    )


def test_a_page_tree_that_fails_when_walked_leaves_as_a_named_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = tmp_path / "order.pdf"
    document.write_bytes(PDF_BYTES)
    monkeypatch.setattr(extraction, "PdfReader", _Reader)

    # ValueError, not PdfReadError: the caller's per-document handler is written against
    # the vocabulary this module promises, and a library exception is not in it.
    with pytest.raises(ValueError) as raised:
        _extract(document)

    assert not isinstance(raised.value, PdfReadError), type(raised.value)
    assert "page tree" in str(raised.value), str(raised.value)


def test_the_construction_guard_is_not_what_catches_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The negative control for the test above: construction must succeed here.

    Without this, a fixture that failed at `PdfReader(...)` would satisfy the assertion
    above through the guard that was already there, and the fix would be untested.
    """
    document = tmp_path / "order.pdf"
    document.write_bytes(PDF_BYTES)
    constructed: list[bool] = []

    class _Watched(_Reader):
        def __init__(self, *arguments: Any, **keywords: Any) -> None:
            super().__init__(*arguments, **keywords)
            constructed.append(True)

    monkeypatch.setattr(extraction, "PdfReader", _Watched)
    with pytest.raises(ValueError):
        _extract(document)

    assert constructed == [True], "the reader never got past construction"


def test_a_readable_page_tree_is_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A guard that refuses every PDF passes the first test perfectly."""

    class _Fine(_Reader):
        def __init__(self, *arguments: Any, **keywords: Any) -> None:
            self.pages: Any = []

    document = tmp_path / "order.pdf"
    document.write_bytes(PDF_BYTES)
    monkeypatch.setattr(extraction, "PdfReader", _Fine)

    with pytest.raises(ValueError) as raised:
        _extract(document)

    # Zero pages with OCR disabled is refused for *that* reason, which is a different
    # sentence. What must not appear is the malformed-tree refusal.
    assert "page tree" not in str(raised.value), str(raised.value)
