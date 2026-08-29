"""A resource ceiling that sits inside the range of real inputs is not a ceiling.

Measured 2026-08-29 on the 57 PDFs the catalogue had captured: 504 · 492 · 480 · 460 ·
432 pages. `max_pdf_pages` was 500. Four documents were within 8% of it and one was four
pages past it — and the one past it was the Statute of Internal Service of the Armed
Forces of Ukraine, the document a serviceman asks about their own rights from. It was not
refused for being unsafe to parse. It was refused for being 0.8% too long.

A guard against memory exhaustion is supposed to sit far above what real work looks like,
so that crossing it means something went wrong. Sitting inside the working range makes it
a coin flip on the next revision of any of four documents, and the flip lands as
`extractor_refused` — which reads as a fact about the source.

So the ceiling is measured against the corpus, not chosen. This test fails when the two
approach each other again, from either direction: a bigger document arriving, or the
limit being lowered.
"""

from __future__ import annotations

import json
from pathlib import Path

from korpus.config import Settings

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "config/corpus/doctrine_catalog_2026.json"
#: The ceiling must stand this far above the largest document actually catalogued. 1.5 is
#: not a round number chosen for comfort: at 1.2 the 504-page Statute would have needed a
#: 605-page limit, which the next long publication would reach.
REQUIRED_HEADROOM = 1.5


def _catalogued_page_counts() -> list[tuple[int, str]]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    counts: list[tuple[int, str]] = []
    for source in catalog["sources"]:
        if not isinstance(source, dict):
            continue
        for holder in ("capture", "document_probe"):
            block = source.get(holder)
            if not isinstance(block, dict):
                continue
            pages = block.get("pages")
            extracted = block.get("text_as_extracted")
            if isinstance(extracted, dict):
                pages = extracted.get("pages", pages)
            if isinstance(pages, int) and not isinstance(pages, bool) and pages > 0:
                counts.append((pages, str(source.get("id"))))
    return counts


def test_the_page_ceiling_stands_above_every_document_the_catalogue_has_read() -> None:
    counts = _catalogued_page_counts()
    assert counts, "no page counts in the catalogue — this test would assert nothing"
    largest, identifier = max(counts)
    limit = Settings.model_fields["max_pdf_pages"].default
    assert limit >= largest * REQUIRED_HEADROOM, (
        f"max_pdf_pages={limit} against a {largest}-page document ({identifier}) — a "
        f"ceiling needs {REQUIRED_HEADROOM}x headroom over real inputs, or it refuses "
        "documents for being long rather than for being dangerous"
    )


def test_the_measurement_would_notice_a_document_that_grew() -> None:
    """The dual. If the ceiling were compared against nothing, it would always pass."""
    counts = _catalogued_page_counts()
    limit = Settings.model_fields["max_pdf_pages"].default
    assert max(counts)[0] * REQUIRED_HEADROOM > limit / 4, (
        "the catalogue's largest document is so far below the ceiling that this test "
        "cannot fail — either the counts stopped being read or the ceiling is arbitrary"
    )
