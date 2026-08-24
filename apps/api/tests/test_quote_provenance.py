"""A quote has to exist in the document it points at.

The chunker joined the tail of one span to the head of the next with a space, and
paragraphs with a blank line. Both manufacture text. The sentence that came out of the
seam existed in no document, and it left the system as a verbatim citation carrying
`quote_hash` and `source_hash` — the hash proving the quote matches itself. Reproduced
end to end on 2026-08-03: `status=answered`, `quote in source == False`,
`support_score=1.0`.

Recorded as §2.0 of docs/operations/ADMISSION_BOUNDARY_2026-08-03.md, the first-order
ground for withholding the system: KORPUS promises to show *where* a statement is
written, and a system that shows a place which does not exist has broken the one
promise it exists for.
"""

from __future__ import annotations

import random
import string

from fastapi.testclient import TestClient
from korpus.api.dependencies import get_answer_service
from korpus.application.answer_query import ExtractiveAnswerService
from korpus.application.policy import PolicyEngine
from korpus.application.risk import RiskThresholds
from korpus.config import get_settings
from korpus.domain.models import Citation, Claim, RetrievedEvidence
from korpus.infrastructure.extraction import ExtractedPage, make_spans

from apps.api.tests.helpers import approve, ingest_text

MARKER = "ПОХОДЖЕННЯ"


def test_every_span_is_a_slice_of_its_page() -> None:
    """The property the seam broke, over a seeded corpus that crosses many seams."""
    source = random.Random(20260804)
    alphabet = string.ascii_letters + " .,абвгдеєжзиіїйклмнопрстуфхцчшщьюя"
    for _ in range(200):
        paragraphs = [
            "".join(source.choice(alphabet) for _ in range(source.randint(1, 900))).strip() or "x"
            for _ in range(source.randint(1, 8))
        ]
        page = ExtractedPage(page=1, text="\n\n".join(paragraphs))

        spans = make_spans([page], max_chars=240, overlap_chars=40, max_spans=1000)

        for span in spans:
            assert str(span["text"]) in page.text, (
                "a span that is not a substring of its page can be quoted as one"
            )


def test_a_span_never_bridges_two_paragraphs_with_invented_separators() -> None:
    first = "Перший абзац закінчується без крапки"
    second = "другий абзац починається з малої літери"
    page = ExtractedPage(page=1, text=f"{first}\n\n{second}")

    spans = make_spans([page], max_chars=100, overlap_chars=20)

    assert all(str(span["text"]) in page.text for span in spans)
    assert not any(f"{first} {second}" in str(span["text"]) for span in spans), (
        "joining the tail to the head with a space manufactures a sentence"
    )


def test_an_answer_quotes_only_text_that_exists_in_the_document(client: TestClient) -> None:
    """End to end, across a document long enough to be split."""
    filler = "Технічні положення інструкції не стосуються обліку записів. " * 40
    body = "\n\n".join(
        [
            f"Маркер {MARKER} фіксується у журналі підрозділу за кожну добу.",
            filler,
            f"Повторна перевірка маркера {MARKER} проводиться командиром підрозділу.",
        ]
    )
    result = ingest_text(client, text=body)
    approve(client, result["version"]["id"])

    answer = client.post("/v1/answers", json={"text": f"де фіксується {MARKER}"}).json()

    assert answer["status"] == "answered", answer["decision_reason"]
    for citation in answer["citations"]:
        assert citation["quote"] in body, (
            f"the answer cited text absent from the document: {citation['quote']!r}"
        )


class ForgingService(ExtractiveAnswerService):
    """An extraction that emits a quote its span does not contain."""

    def _extract(
        self,
        eligible: list[RetrievedEvidence],
        query_tokens: frozenset[str],
        thresholds: RiskThresholds,
    ) -> tuple[list[Claim], list[Citation], set[str]]:
        import hashlib

        claims, citations, covered = super()._extract(eligible, query_tokens, thresholds)
        if citations:
            forged = "Речення, якого немає в жодному документі корпусу."
            citations[0] = citations[0].model_copy(
                update={
                    "quote": forged,
                    "quote_hash": hashlib.sha256(forged.encode("utf-8")).hexdigest(),
                },
                deep=True,
            )
        return claims, citations, covered


def test_a_quote_absent_from_its_span_stops_the_answer(client: TestClient) -> None:
    """The second line: chunking may change again, the promise may not."""
    result = ingest_text(client, text=f"Маркер {MARKER} фіксується у журналі підрозділу.")
    approve(client, result["version"]["id"])
    real = get_answer_service(
        client.app.state.repository,
        PolicyEngine(),
        client.app.dependency_overrides[get_settings](),
        client.app.state.query_cache,
        client.app.state.semantic_source,
    )
    service = ForgingService(
        client.app.state.repository, real.retriever, PolicyEngine(), real.answer_policy
    )
    client.app.dependency_overrides[get_answer_service] = lambda: service

    answer = client.post("/v1/answers", json={"text": f"де фіксується {MARKER}"}).json()

    assert answer["status"] == "requires_human_review"
    assert answer["decision_reason"] == "citation_not_present_in_source"
    assert answer["citations"] == []
