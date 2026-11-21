"""A short page containing two headings must not lend the first address to both."""

from __future__ import annotations

import hashlib
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient
from korpus.domain.models import ExtractedPage
from korpus.infrastructure.extraction import make_spans, section_markers

from apps.api.tests.helpers import approve, ingest_text

FIRST = "РОЗДІЛ 1. Осінній архів"
SECOND = "РОЗДІЛ 2. Весняний архів"
FIRST_FACT = "Колір коробки Абрикос — червоний."
SECOND_FACT = "Колір коробки Смарагд — синій."
SOURCE = f"{FIRST}\n\n{FIRST_FACT}\n\n{SECOND}\n\n{SECOND_FACT}"


def test_short_spans_cannot_assign_the_previous_section_to_a_later_fact() -> None:
    spans = make_spans([ExtractedPage(page=7, text=SOURCE)])

    assert len(spans) == 2
    assert [(span["section"], span["text"]) for span in spans] == [
        (FIRST, f"{FIRST}\n\n{FIRST_FACT}"),
        (SECOND, f"{SECOND}\n\n{SECOND_FACT}"),
    ]
    assert [span["ordinal"] for span in spans] == [0, 1]
    assert all(span["page"] == 7 and span["text"] in SOURCE for span in spans)


@pytest.mark.parametrize(
    ("question", "fact", "section"),
    [
        ("Який колір коробки Абрикос?", FIRST_FACT, FIRST),
        ("Який колір коробки Смарагд?", SECOND_FACT, SECOND),
    ],
    ids=["first-section", "second-section"],
)
def test_answer_citation_uses_the_quoted_facts_section_and_exact_offsets(
    client: TestClient, question: str, fact: str, section: str
) -> None:
    ingested = ingest_text(client, title="Нейтральний архів кольорів", text=SOURCE)
    approve(client, ingested["version"]["id"])

    response = client.post("/v1/answers", json={"text": question})
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["status"] == "answered", answer
    relevant = [citation for citation in answer["citations"] if fact in citation["quote"]]
    assert relevant, answer
    for citation in relevant:
        assert citation["section"] == section
        span = client.get(f"/v1/spans/{citation['span_id']}").json()
        assert span["section"] == section
        assert span["text"] in SOURCE
        assert span["text"][citation["quote_start"] : citation["quote_end"]] == citation["quote"]
        assert citation["quote"] in SOURCE
        assert citation["quote_hash"] == hashlib.sha256(citation["quote"].encode()).hexdigest()
        assert citation["span_hash"] == hashlib.sha256(span["text"].encode()).hexdigest()


@pytest.mark.parametrize("overlap", [0, 30, 99])
def test_bounded_overlap_progress_and_coverage_hold_inside_each_section(overlap: int) -> None:
    before = "Archive introduction.\n\n"
    parts = [
        f"РОЗДІЛ {index}. Архів\n\n" + " ".join(f"color{index:02}_{word:03}" for word in range(35))
        for index in range(1, 4)
    ]
    text = before + "\n\n".join(parts)
    spans = make_spans(
        [ExtractedPage(page=1, text=text)], max_chars=100, overlap_chars=overlap, max_spans=1500
    )
    markers = section_markers(text)
    covered: set[int] = set()
    starts = []
    for span in spans:
        chunk = str(span["text"])
        start = text.index(chunk)
        end = start + len(chunk)
        starts.append(start)
        assert 0 < len(chunk) <= 100
        assert not any(start < boundary < end for boundary, _label in markers)
        expected = [label for boundary, label in markers if boundary <= start]
        assert span["section"] == (expected[-1] if expected else None)
        covered.update(range(start, end))
    # Leading whitespace can make two raw positions trim to the same slice start.
    # Raw positions still advance by at least one, bounding the number of outputs.
    assert all(left <= right for left, right in pairwise(starts))
    assert len(spans) <= len(text)
    assert all(index in covered for index, character in enumerate(text) if not character.isspace())
    assert [span["ordinal"] for span in spans] == list(range(len(spans)))


def test_adjacent_and_indented_headings_do_not_create_empty_or_mislabeled_spans() -> None:
    text = f"  {FIRST}\n\n\t{SECOND}\n\n{SECOND_FACT}"
    spans = make_spans([ExtractedPage(page=None, text=text)])

    assert [span["section"] for span in spans] == [FIRST, SECOND]
    assert [span["text"] for span in spans] == [FIRST, f"{SECOND}\n\n{SECOND_FACT}"]
    assert all(span["text"] in text for span in spans)


def test_many_section_boundaries_cannot_bypass_the_span_count_limit() -> None:
    text = "\n\n".join(f"РОЗДІЛ {index}. Архів\n\nColor record {index}." for index in range(4))

    with pytest.raises(ValueError, match="maximum span count"):
        make_spans([ExtractedPage(page=1, text=text)], max_spans=3)


def test_plain_pages_keep_exact_substrings_without_invented_sections() -> None:
    pages = [
        ExtractedPage(page=1, text="Archive red. " * 20),
        ExtractedPage(page=2, text="Archive blue."),
    ]
    spans = make_spans(pages, max_chars=100, overlap_chars=20)

    assert all(span["section"] is None for span in spans)
    assert all(span["text"] in pages[span["page"] - 1].text for span in spans)
