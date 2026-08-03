"""The three validity boundaries, one test per side.

On 2026-08-03 a mutation of `is_valid_on` — changing `as_of > effective_until` to
`as_of >= effective_until`, which moves the end of a document's validity by a full
day — was applied to this tree and the entire suite passed. Nothing anywhere stated
which day belonged to which side, so both readings were equally defensible and
neither was defended.

The semantics are now written down in docs/architecture/DATA_MODEL.md. These tests
are the executable half of that statement: each one fails if its boundary shifts by
one day in either direction, so the choice cannot be undone by accident.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from korpus.domain.models import AuthorityClass, DocumentVersionRecord

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
