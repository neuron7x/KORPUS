"""A reader has to be able to open the passage the answer points at.

Destruction stage, MAJOR: `section` was always None, `page` empty for text formats,
there was no endpoint that returns a span (`/v1/spans`,
`/v1/document-versions/{id}/spans`, `/text` all 404), and `quote_hash` is the hash of
the quote itself — a hash proving the quote matches itself. The one promise KORPUS
makes is to show *where* a statement is written, and nothing in the system let anyone
go and look.

The chain a reader can now walk without trusting the answer object:
  quote → `quote_hash` over the quote, and `span.text[quote_start:quote_end]` equal to
  it → `span_hash` over the span's own text → `source_hash` over the document bytes.
Every link is checkable from the API, and the middle link is the one that used to be
missing.

Disclosure is the same filter as retrieval: the endpoints answer out of
`list_retrievable_spans` / `get_retrievable_spans_by_ids`, so a reader can reach
exactly the material an answer could have cited them, on the date they ask about.
"""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient
from korpus.domain.models import AccessTier, Identity

from apps.api.tests.conftest import set_identity
from apps.api.tests.helpers import approve, ingest_text

MARKER = "ФРАГМЕНТ"
STRUCTURED = f"""Розділ I
Загальні положення

Стаття 5. Ведення журналу

Журнал {MARKER} ведеться щодоби відповідальною особою підрозділу.

Стаття 6. Зберігання

Журнал {MARKER} зберігається протягом трьох років у сховищі частини.
"""


def test_the_spans_of_a_version_can_be_listed(client: TestClient) -> None:
    result = ingest_text(client, text=STRUCTURED)
    version_id = result["version"]["id"]
    approve(client, version_id)

    response = client.get(f"/v1/document-versions/{version_id}/spans")

    assert response.status_code == 200, response.text
    spans = response.json()
    assert spans, "an approved version must expose the passages it was indexed as"
    assert [span["ordinal"] for span in spans] == sorted(span["ordinal"] for span in spans)
    for span in spans:
        assert span["text_hash"] == hashlib.sha256(span["text"].encode("utf-8")).hexdigest()


def test_a_span_carries_the_section_it_sits_under(client: TestClient) -> None:
    """`section` was always None, so a citation had no address a reader could check."""
    result = ingest_text(client, text=STRUCTURED)
    approve(client, result["version"]["id"])

    spans = client.get(f"/v1/document-versions/{result['version']['id']}/spans").json()

    sections = {span["section"] for span in spans}
    assert sections != {None}, spans
    assert all(section for section in sections), spans


def test_the_answer_citation_resolves_to_a_span_that_contains_the_quote(
    client: TestClient,
) -> None:
    """The link that was missing: quote → span → document."""
    result = ingest_text(client, text=STRUCTURED)
    approve(client, result["version"]["id"])

    answer = client.post("/v1/answers", json={"text": f"як ведеться журнал {MARKER}"}).json()
    assert answer["status"] == "answered", answer["decision_reason"]
    citation = answer["citations"][0]

    span = client.get(f"/v1/spans/{citation['span_id']}").json()

    assert span["text"][citation["quote_start"] : citation["quote_end"]] == citation["quote"]
    assert span["text_hash"] == citation["span_hash"]
    assert (
        hashlib.sha256(citation["quote"].encode("utf-8")).hexdigest() == citation["quote_hash"]
    )


def test_a_reader_cannot_open_a_span_they_could_not_have_been_cited(
    client: TestClient,
) -> None:
    """Disclosure runs through the retrieval filter, not around it."""
    restricted = ingest_text(
        client,
        title="Обмежений наказ",
        corpus_id="restricted-demo",
        access_tier=3,
        classification="restricted",
        text=f"Маркер {MARKER} доступний лише в обмеженому корпусі частини.",
    )
    approve(client, restricted["version"]["id"])
    version_id = restricted["version"]["id"]
    spans = client.get(f"/v1/document-versions/{version_id}/spans").json()
    span_id = spans[0]["id"]

    set_identity(
        client,
        Identity(
            subject="public-reader",
            roles=frozenset({"user"}),
            clearance=AccessTier.PUBLIC,
            corpora=frozenset({"public"}),
        ),
    )

    assert client.get(f"/v1/spans/{span_id}").status_code == 404
    assert client.get(f"/v1/document-versions/{version_id}/spans").json() == []


def test_a_span_is_not_disclosed_on_a_date_the_version_did_not_govern(
    client: TestClient,
) -> None:
    """The same currency rule as retrieval: `as_of` decides, here too."""
    from datetime import date

    result = ingest_text(client, text=STRUCTURED, effective_from=date(2026, 6, 1))
    version_id = result["version"]["id"]
    approve(client, version_id)

    before = client.get(
        f"/v1/document-versions/{version_id}/spans", params={"as_of": "2026-05-31"}
    ).json()
    on_the_day = client.get(
        f"/v1/document-versions/{version_id}/spans", params={"as_of": "2026-06-01"}
    ).json()

    assert before == []
    assert on_the_day
