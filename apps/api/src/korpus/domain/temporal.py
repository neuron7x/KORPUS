"""Pure temporal-validity predicate shared by domain and projection paths."""
from __future__ import annotations
from datetime import date, datetime


def version_is_valid_on_fields(as_of: date, *, publication_date: date | None,
                               effective_from: date | None, effective_until: date | None,
                               rescinded_at: datetime | None) -> bool:
    start = effective_from or publication_date
    if start is None or start > as_of:
        return False
    if effective_until is not None and effective_until < as_of:
        return False
    if rescinded_at is not None and rescinded_at.date() <= as_of:
        return False
    return True
