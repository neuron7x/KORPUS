"""One ISO-date parser for the gates that read a measurement date."""

from __future__ import annotations

from datetime import date, datetime


def iso_date(value: str) -> date:
    """A date from an ISO string, in every form that names one moment — and only those.

    `date.fromisoformat` in 3.12 refuses `2026-08-29T10:00:00`, the most common way to write
    when a measurement was taken, and silently accepts `20260829` and `2026-W35-6`, which no
    probe here writes. Its message said the input "is not an ISO date", which is false: it
    sends the reader to look for a defect in the data rather than in the parser — the same
    failure as a STALE that says the tree changed when it did not.

    Shape is checked before parsing, not after: writing the check second let
    `datetime.fromisoformat("20260829")` succeed and return before the check ran, which is
    how the first version of this fix still accepted both forms.

    Found by an equivalent-input probe, not a poison. Every live date in these catalogs is
    YYYY-MM-DD, so no corruption of the data could expose it — only the same moment written
    another way. Shared by three gates that each had the same call.
    """
    head = value.split("T", 1)[0]
    if len(head) != 10 or head[4] != "-" or head[7] != "-":
        raise ValueError(
            f"{value!r} does not begin with a YYYY-MM-DD date — a compact or week-numbered "
            "form names a real day but is a data error here, not a spelling"
        )
    return datetime.fromisoformat(value).date()
