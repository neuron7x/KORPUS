"""A library copy carries the date it was seen, not the date the document took force.

The corpus is fed from a shared Drive folder of military literature. For almost none of
it is a publication date established: the fetcher records when the *copy* was last
modified, and `build_import_manifest.py --from-snapshot` writes that into
`effective_from` so the source can never be cited as governing an earlier date.

That is a conservative floor, and it is the right one. But `effective_from` reads on the
answer surface exactly like a date of issue, and a reader who takes it for one has been
told something the field cannot support — that somebody established when this document
was published. The answer has to say the difference out loud, per citation, or the floor
becomes a claim.

Negative control included: a version that *does* state a publication date must not carry
the notice. A limitation attached to everything says nothing.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from apps.api.tests.helpers import approve, ingest_text

MARKER = "НЕДАТОВАНЕ"
BODY = f"Джерело {MARKER} описує порядок огляду техніки перед виходом."
NOTICE = "без встановленої дати публікації"


def _answer(client: TestClient) -> dict[str, object]:
    response = client.post("/v1/answers", json={"text": f"порядок {MARKER}"})
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_a_citation_without_a_publication_date_says_so(client: TestClient) -> None:
    result = ingest_text(client, text=BODY, effective_from=date(2024, 3, 11), publication_date=None)
    approve(client, result["version"]["id"])

    answer = _answer(client)

    assert answer["status"] == "answered", answer["decision_reason"]
    limitations = [str(item) for item in answer["limitations"]]  # type: ignore[union-attr]
    assert any(NOTICE in item for item in limitations), limitations
    assert any("дата копії" in item for item in limitations), limitations


def test_a_dated_source_carries_no_such_notice(client: TestClient) -> None:
    """The negative control: if it fires for a dated source, it measures nothing."""
    result = ingest_text(client, text=BODY, publication_date=date(2024, 3, 11))
    approve(client, result["version"]["id"])

    answer = _answer(client)

    assert answer["status"] == "answered", answer["decision_reason"]
    limitations = [str(item) for item in answer["limitations"]]  # type: ignore[union-attr]
    assert not any(NOTICE in item for item in limitations), limitations


def test_the_notice_counts_citations_not_versions(client: TestClient) -> None:
    """One undated version cited twice is one source, and the count must not inflate."""
    longer = (
        f"Джерело {MARKER} описує порядок огляду техніки перед виходом."
        f" Джерело {MARKER} також визначає перелік вузлів для перевірки."
    )
    result = ingest_text(
        client, text=longer, effective_from=date(2024, 3, 11), publication_date=None
    )
    approve(client, result["version"]["id"])

    answer = _answer(client)

    citations = answer["citations"]
    assert isinstance(citations, list)
    limitations = [str(item) for item in answer["limitations"]]  # type: ignore[union-attr]
    notice = next(item for item in limitations if NOTICE in item)
    assert notice.split()[0] == str(len(citations)), (notice, len(citations))
