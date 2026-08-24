"""An audit event has to say which edition governed the answer, and on what date.

Destruction stage, MAJOR: `answer.completed` recorded counts — how many spans were
retrieved, how many were eligible, how many citations shipped — and none of the things
an investigation asks for. Which version governed, which span was quoted, what `as_of`
was in force and which thresholds were applied were all absent, so reconstructing after
the fact why one answer was given and another withheld was impossible from the record.

For a system whose output is material for a human decision, the record of *what it
stood on* is the part that outlives the answer.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from apps.api.tests.helpers import approve, ingest_text

MARKER = "АУДИТОРСЬКИЙ"


def _completed_event(client: TestClient, trace_id: str) -> dict[str, Any]:
    events = client.get("/v1/audit/events", params={"trace_id": trace_id}).json()
    completed = [event for event in events if event["action"] == "answer.completed"]
    assert completed, f"no answer.completed event for trace {trace_id}: {events}"
    payload: dict[str, Any] = completed[-1]["payload"]
    return payload


def _ask(client: TestClient, text: str, **body: Any) -> tuple[dict[str, Any], str]:
    response = client.post("/v1/answers", json={"text": text, **body})
    assert response.status_code == 200, response.text
    trace_id = response.headers["x-request-id"]
    return response.json(), trace_id


def test_the_event_names_the_version_and_span_the_answer_stood_on(
    client: TestClient,
) -> None:
    result = ingest_text(
        client, text=f"Журнал {MARKER} ведеться у підрозділі щодоби відповідальною особою."
    )
    approve(client, result["version"]["id"])

    answer, trace_id = _ask(client, f"як ведеться журнал {MARKER}")
    assert answer["status"] == "answered", answer["decision_reason"]

    payload = _completed_event(client, trace_id)

    cited = payload["citations"]
    assert cited, payload
    assert {entry["version_id"] for entry in cited} == {
        citation["version_id"] for citation in answer["citations"]
    }
    assert {entry["span_id"] for entry in cited} == {
        citation["span_id"] for citation in answer["citations"]
    }
    assert all(entry["quote_hash"] for entry in cited)


def test_the_event_records_the_date_the_answer_was_given_for(client: TestClient) -> None:
    """`as_of` decides which edition is current; an audit without it is undecidable."""
    result = ingest_text(client, text=f"Журнал {MARKER} ведеться у підрозділі щодоби.")
    approve(client, result["version"]["id"])

    _answer, trace_id = _ask(client, f"як ведеться журнал {MARKER}", as_of="2026-08-04")

    assert _completed_event(client, trace_id)["as_of"] == "2026-08-04"


def test_the_event_records_the_thresholds_that_were_applied(client: TestClient) -> None:
    """Risk raises the bar per request, so the bar is part of the record."""
    result = ingest_text(client, text=f"Журнал {MARKER} ведеться у підрозділі щодоби.")
    approve(client, result["version"]["id"])

    _answer, trace_id = _ask(client, f"який порядок ведення журналу {MARKER} обовязково")

    thresholds = _completed_event(client, trace_id)["thresholds"]
    assert set(thresholds) == {
        "minimum_score",
        "minimum_query_coverage",
        "minimum_support_score",
        "minimum_authority",
    }
    assert all(isinstance(value, float) for value in thresholds.values())


def test_an_abstention_records_the_same_fields(client: TestClient) -> None:
    """The withheld answer is the one an investigation is most likely to ask about."""
    _answer, trace_id = _ask(client, "питання без жодного джерела у корпусі взагалі")

    payload = _completed_event(client, trace_id)

    assert payload["citations"] == []
    assert payload["as_of"]
    assert payload["thresholds"]
