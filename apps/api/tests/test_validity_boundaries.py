"""The three validity boundaries, one test per side.

On 2026-08-03 a mutation of `is_valid_on` — changing `as_of > effective_until` to
`as_of >= effective_until`, which moves the end of a document's validity by a full
day — was applied to this tree and the entire suite passed. Nothing anywhere stated
which day belonged to which side, so both readings were equally defensible and
neither was defended.

The semantics are now written down in docs/architecture/DATA_MODEL.md. These tests
are the executable half of that statement: each one fails if its boundary shifts by
one day in either direction, so the choice cannot be undone by accident.

The domain half is not sufficient on its own. The candidate query in
`_candidate_span_ids` repeats the same three boundaries in SQL, and only the domain
copy was defended: shifting `v.effective_until >= :as_of` to `>` there drops a
document on the last day it governs, and `_materialize_current` cannot restore a row
the search never returned. The second half of this file therefore asserts the SQL
path and the domain agree date by date, so either copy moving alone is a failure.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from korpus.domain.models import AuthorityClass, DocumentVersionRecord
from korpus.infrastructure.repository import versions
from sqlalchemy import update

from apps.api.tests.conftest import privileged_connection
from apps.api.tests.helpers import approve, ingest_text

DAY = date(2026, 6, 15)
BEFORE = date(2026, 6, 14)
AFTER = date(2026, 6, 16)


def _version(**overrides: object) -> DocumentVersionRecord:
    fields: dict[str, object] = {
        "document_id": uuid4(),
        "revision": "1.0",
        "source_hash": "a" * 64,
        "object_key": "objects/test",
        "mime_type": "text/plain",
        "authority": AuthorityClass.OFFICIAL_UA,
        # A version with neither effective_from nor publication_date governs no date
        # at all (test_currency_lower_bound.py); these cases are about the upper
        # bound and the rescission boundary, so the lower one is pinned in the past.
        "publication_date": date(2020, 1, 1),
    }
    fields.update(overrides)
    return DocumentVersionRecord.model_validate(fields)


def test_a_version_takes_effect_on_the_day_it_names() -> None:
    """effective_from is inclusive: the named day is the first day of validity."""
    version = _version(effective_from=DAY)

    assert version.is_valid_on(BEFORE) is False
    assert version.is_valid_on(DAY) is True, (
        "a document effective from D must govern an answer asked on D, not from D+1"
    )


def test_a_version_still_governs_on_the_last_day_it_names() -> None:
    """effective_until is inclusive: «чинний до 31 грудня» includes the 31st."""
    version = _version(effective_until=DAY)

    assert version.is_valid_on(DAY) is True, (
        "a document valid until D must still govern an answer asked on D"
    )
    assert version.is_valid_on(AFTER) is False, (
        "and it must stop governing the next day — otherwise expiry never happens"
    )


def test_a_rescinded_version_stops_governing_on_the_day_of_rescission() -> None:
    """rescinded_at is exclusive, and it is an act rather than a term."""
    version = _version(rescinded_at=datetime(2026, 6, 15, 9, 30, tzinfo=UTC))

    assert version.is_valid_on(BEFORE) is True
    assert version.is_valid_on(DAY) is False, (
        "rescission takes effect on its own day; a term expires at the end of its last"
    )


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (date(2026, 6, 13), False),
        (date(2026, 6, 14), True),
        (date(2026, 6, 15), True),
        (date(2026, 6, 16), True),
        (date(2026, 6, 17), False),
    ],
)
def test_the_closed_interval_holds_at_both_ends(as_of: date, expected: bool) -> None:
    """Both bounds together: [effective_from, effective_until] is closed on both sides."""
    version = _version(effective_from=BEFORE, effective_until=AFTER)

    assert version.is_valid_on(as_of) is expected


MARKER = "ГРАНИЧНИЙ"
BODY = f"Маркер {MARKER} діє рівно у названий строк і жодного дня понад нього."


def _ask(client, as_of: date) -> dict[str, object]:
    response = client.post(
        "/v1/answers",
        json={"text": f"що означає {MARKER}", "as_of": as_of.isoformat()},
    )
    assert response.status_code == 200, response.text
    payload: dict[str, object] = response.json()
    return payload


def _sql_verdicts(client, span_id: str, identity, days: list[date]) -> dict[date, bool]:
    """What the SQL candidate query alone says, one date at a time."""
    repository = client.app.state.repository
    verdicts: dict[date, bool] = {}
    for day in days:
        rows = repository.search_retrievable_spans(
            identity, frozenset({"public"}), day, MARKER, 20
        )
        verdicts[day] = any(str(span.id) == span_id for span, _, _ in rows)
    return verdicts


def test_the_search_path_keeps_a_document_on_the_last_day_it_names(client, admin_identity) -> None:
    """The end boundary again, through SQL this time: `>=` there, not `>`."""
    result = ingest_text(client, effective_until=DAY, text=BODY)
    approve(client, result["version"]["id"])

    on_the_day = _ask(client, DAY)
    the_day_after = _ask(client, AFTER)

    assert on_the_day["status"] == "answered", (
        "an order valid until D must still be retrievable on D; the SQL candidate "
        "filter is the only place that can drop it before the domain is consulted"
    )
    assert on_the_day["citations"], "answered without a citation is not an answer"
    assert the_day_after["status"] == "insufficient_evidence"
    assert the_day_after["citations"] == []


def test_the_search_path_withholds_a_document_before_it_takes_effect(
    client, admin_identity
) -> None:
    """The start boundary through SQL: a future order governs nothing today."""
    result = ingest_text(client, effective_from=DAY, text=BODY)
    approve(client, result["version"]["id"])

    assert _ask(client, BEFORE)["status"] == "insufficient_evidence"
    assert _ask(client, DAY)["status"] == "answered"


def test_sql_and_domain_agree_on_every_day_around_both_bounds(client, admin_identity) -> None:
    """Neither copy of the boundary may move without the other."""
    result = ingest_text(client, effective_from=BEFORE, effective_until=AFTER, text=BODY)
    version_id = result["version"]["id"]
    approve(client, version_id)
    span_id = str(
        client.app.state.repository.list_retrievable_spans(
            admin_identity, frozenset({"public"}), DAY
        )[0][0].id
    )
    version = client.app.state.repository.get_version(admin_identity, UUID(version_id))
    assert version is not None
    days = [BEFORE - timedelta(days=1), BEFORE, DAY, AFTER, AFTER + timedelta(days=1)]

    sql = _sql_verdicts(client, span_id, admin_identity, days)

    for day in days:
        assert sql[day] is version.is_valid_on(day), (
            f"SQL and domain disagree on {day.isoformat()}: SQL says {sql[day]}, "
            f"domain says {version.is_valid_on(day)}"
        )


def test_rescission_removes_the_document_from_search_on_its_own_day(
    client, admin_identity
) -> None:
    """`rescinded_at` has no ingestion path yet, so the row is set directly.

    The boundary still has to hold: the SQL candidate query uses
    `date(v.rescinded_at) > :as_of`, and that strictness is what makes rescission
    take effect on the day it happens rather than the day after.
    """
    result = ingest_text(client, text=BODY)
    version_id = result["version"]["id"]
    approve(client, version_id)
    with privileged_connection(client) as connection:
        connection.execute(
            update(versions)
            .where(versions.c.id == version_id)
            .values(rescinded_at=datetime(DAY.year, DAY.month, DAY.day, 9, 30, tzinfo=UTC))
        )

    assert _ask(client, BEFORE)["status"] == "answered"
    assert _ask(client, DAY)["status"] == "insufficient_evidence", (
        "a rescinded order must stop governing on the day of rescission"
    )


@pytest.mark.parametrize(
    ("field", "asked_on"),
    [
        ("effective_until", AFTER),
        ("effective_from", BEFORE),
        ("rescinded_at", DAY),
    ],
)
def test_the_candidate_query_alone_excludes_an_invalid_version(
    client, admin_identity, field: str, asked_on: date
) -> None:
    """The SQL half must be right on its own, not merely covered by the domain half.

    `_materialize_current` re-checks validity in Python, so a SQL filter that leaks an
    expired candidate produces the same answer and no behavioural test can see it. The
    leak is still real: it spends the candidate budget on rows that cannot be cited and
    puts the whole boundary on a single point of failure. This asserts the SQL layer
    separately, at the one date where the boundary is decided.
    """
    kwargs = {} if field == "rescinded_at" else {field: DAY}
    result = ingest_text(client, text=BODY, **kwargs)
    version_id = result["version"]["id"]
    approve(client, version_id)
    repository = client.app.state.repository
    if field == "rescinded_at":
        with privileged_connection(client) as connection:
            connection.execute(
                update(versions)
                .where(versions.c.id == version_id)
                .values(rescinded_at=datetime(DAY.year, DAY.month, DAY.day, 9, 30, tzinfo=UTC))
            )

    with privileged_connection(client) as connection:
        candidates = repository._candidate_span_ids(
            admin_identity, frozenset({"public"}), asked_on, MARKER, 20, connection
        )

    assert candidates == [], (
        f"the candidate query returned a version that {field} had already excluded "
        f"on {asked_on.isoformat()}"
    )
