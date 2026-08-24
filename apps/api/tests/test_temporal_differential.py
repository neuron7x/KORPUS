from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

from korpus.domain.temporal import version_is_valid_on_fields


def _reference(as_of, publication_date, effective_from, effective_until, rescinded_at):
    start = effective_from or publication_date
    return bool(
        start is not None
        and start <= as_of
        and (effective_until is None or effective_until >= as_of)
        and (rescinded_at is None or rescinded_at.date() > as_of)
    )


def test_temporal_predicate_matches_reference_over_seeded_state_space():
    rng = random.Random(20260820)
    origin = date(2026, 1, 1)
    for _ in range(2000):
        as_of = origin + timedelta(days=rng.randint(-400, 400))
        publication = (
            None if rng.random() < 0.15 else origin + timedelta(days=rng.randint(-500, 300))
        )
        effective = None if rng.random() < 0.5 else origin + timedelta(days=rng.randint(-500, 300))
        until = None if rng.random() < 0.6 else origin + timedelta(days=rng.randint(-200, 600))
        rescinded = (
            None
            if rng.random() < 0.7
            else datetime.combine(
                origin + timedelta(days=rng.randint(-200, 600)), datetime.min.time(), tzinfo=UTC
            )
        )
        expected = _reference(as_of, publication, effective, until, rescinded)
        observed = version_is_valid_on_fields(
            as_of,
            publication_date=publication,
            effective_from=effective,
            effective_until=until,
            rescinded_at=rescinded,
        )
        assert observed is expected
