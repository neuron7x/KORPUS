"""Feedback from the person who acted on the answer, and the trail that explains it."""

from __future__ import annotations

from uuid import uuid4

from conftest import CORPUS, make_span
from korpus.api import routes
from korpus.domain.access import Principal
from korpus.domain.models import AccessTier
from korpus.infrastructure.resilience import TokenBucket


def reviewer() -> Principal:
    return Principal(
        subject_id="reviewer-1",
        tier=AccessTier.REVIEWED,
        authorized_corpora=frozenset({CORPUS}),
    )


def test_feedback_is_recorded_against_the_trace_it_refers_to(client) -> None:  # type: ignore[no-untyped-def]
    routes._retriever.add(make_span(text="порядок евакуації поранених"))
    answer = client.post("/v1/answers", json={"text": "порядок евакуації"}).json()

    response = client.post(
        "/v1/feedback",
        json={"trace_id": answer["trace_id"], "verdict": "wrong", "comment": "не той пункт"},
    )
    assert response.status_code == 200
    assert response.json() == {"recorded": True, "trace_id": answer["trace_id"]}
    event, payload = routes._audit.events[-1]
    assert event == "answer.feedback"
    assert payload["verdict"] == "wrong"
    assert payload["comment"] == "не той пункт"


def test_a_dangerous_verdict_is_its_own_category(client) -> None:  # type: ignore[no-untyped-def]
    """"Wrong" and "would have got someone hurt" must not aggregate into one number."""
    response = client.post(
        "/v1/feedback", json={"trace_id": str(uuid4()), "verdict": "dangerous"}
    )
    assert response.status_code == 200
    assert routes._audit.events[-1][1]["verdict"] == "dangerous"


def test_an_unknown_verdict_is_rejected(client) -> None:  # type: ignore[no-untyped-def]
    response = client.post(
        "/v1/feedback", json={"trace_id": str(uuid4()), "verdict": "погано"}
    )
    assert response.status_code == 422


def test_feedback_requires_a_trace_id(client) -> None:  # type: ignore[no-untyped-def]
    assert client.post("/v1/feedback", json={"verdict": "helpful"}).status_code == 422


def test_feedback_refuses_unknown_fields(client) -> None:  # type: ignore[no-untyped-def]
    payload = {"trace_id": str(uuid4()), "verdict": "helpful", "rating": 5}
    assert client.post("/v1/feedback", json=payload).status_code == 422


def test_feedback_is_rate_limited(client) -> None:  # type: ignore[no-untyped-def]
    routes._bucket = TokenBucket(capacity=1, refill_per_second=0)
    first = client.post("/v1/feedback", json={"trace_id": str(uuid4()), "verdict": "helpful"})
    second = client.post("/v1/feedback", json={"trace_id": str(uuid4()), "verdict": "helpful"})
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["recorded"] is False


def test_feedback_reports_when_it_cannot_be_recorded(client) -> None:  # type: ignore[no-untyped-def]
    """Silently dropping a correction is worse than refusing it."""
    routes._audit = None
    response = client.post(
        "/v1/feedback", json={"trace_id": str(uuid4()), "verdict": "wrong"}
    )
    assert response.status_code == 503
    assert response.json()["recorded"] is False


def test_an_auditor_can_reconstruct_why_an_answer_was_shown(client) -> None:  # type: ignore[no-untyped-def]
    routes._retriever.add(make_span(text="порядок евакуації поранених"))
    answer = client.post("/v1/answers", json={"text": "порядок евакуації"}).json()
    routes._resolver.trust("auditor", reviewer())

    response = client.get(
        f"/v1/audit/{answer['trace_id']}", headers={"Authorization": "Bearer auditor"}
    )
    assert response.status_code == 200
    events = response.json()["events"]
    assert [event["event"] for event in events] == ["answer.completed"]
    assert events[0]["payload"]["status"] == "answered"
    assert events[0]["payload"]["eligible"] == 1


def test_the_trail_covers_a_refusal_as_well_as_an_answer(client) -> None:  # type: ignore[no-untyped-def]
    denied = client.post(
        "/v1/answers", json={"text": "порядок евакуації", "corpus_ids": [str(uuid4())]}
    ).json()
    routes._resolver.trust("auditor", reviewer())
    events = client.get(
        f"/v1/audit/{denied['trace_id']}", headers={"Authorization": "Bearer auditor"}
    ).json()["events"]
    assert events[0]["payload"]["status"] == "access_denied"
    assert events[0]["payload"]["denial_reason"] == "corpus_not_authorized"


def test_an_anonymous_reader_cannot_read_the_audit_trail(client) -> None:  # type: ignore[no-untyped-def]
    """The trail describes what other people asked and what they were shown."""
    response = client.get(f"/v1/audit/{uuid4()}")
    assert response.status_code == 403
    assert response.json()["status"] == "access_denied"
    assert response.json()["events"] == []


def test_an_unknown_trace_is_reported_as_missing_not_as_empty_success(client) -> None:  # type: ignore[no-untyped-def]
    routes._resolver.trust("auditor", reviewer())
    response = client.get(
        f"/v1/audit/{uuid4()}", headers={"Authorization": "Bearer auditor"}
    )
    assert response.status_code == 404
    assert response.json()["status"] == "not_found"


def test_the_trail_reports_degraded_without_a_store(client) -> None:  # type: ignore[no-untyped-def]
    routes._resolver.trust("auditor", reviewer())
    routes._store = None
    response = client.get(
        f"/v1/audit/{uuid4()}", headers={"Authorization": "Bearer auditor"}
    )
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_search_events_are_visible_to_the_auditor(client) -> None:  # type: ignore[no-untyped-def]
    routes._retriever.add(make_span(text="порядок евакуації поранених"))
    search = client.post("/v1/search", json={"text": "порядок евакуації"}).json()
    routes._resolver.trust("auditor", reviewer())
    events = client.get(
        f"/v1/audit/{search['trace_id']}", headers={"Authorization": "Bearer auditor"}
    ).json()["events"]
    assert events[0]["event"] == "search.completed"
