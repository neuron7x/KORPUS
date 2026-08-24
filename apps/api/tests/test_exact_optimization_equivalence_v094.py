from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from korpus.domain.models import AuthorityClass, DocumentVersionRecord, ReviewState, version_is_valid_on_fields


def _version(*, publication_date, effective_from, effective_until, rescinded_at):
    return DocumentVersionRecord(
        id=uuid4(),
        document_id=uuid4(),
        revision="r",
        source_hash="a" * 64,
        object_key="o",
        mime_type="text/plain",
        publication_date=publication_date,
        effective_from=effective_from,
        effective_until=effective_until,
        rescinded_at=rescinded_at,
        authority=AuthorityClass.UNKNOWN,
        review_state=ReviewState.APPROVED,
    )


def test_projection_currency_fast_path_is_exactly_domain_equivalent() -> None:
    rng = random.Random(0x094)
    epoch = date(2020, 1, 1)
    for _ in range(500):
        publication = None if rng.randrange(4) == 0 else epoch + timedelta(days=rng.randrange(2500))
        effective = None if rng.randrange(3) else epoch + timedelta(days=rng.randrange(2500))
        until = None if rng.randrange(3) else epoch + timedelta(days=rng.randrange(2500))
        rescinded = None
        if rng.randrange(3) == 0:
            d = epoch + timedelta(days=rng.randrange(2500))
            rescinded = datetime(d.year, d.month, d.day, 12, tzinfo=UTC)
        as_of = epoch + timedelta(days=rng.randrange(2500))
        version = _version(
            publication_date=publication,
            effective_from=effective,
            effective_until=until,
            rescinded_at=rescinded,
        )
        assert version_is_valid_on_fields(
            as_of,
            publication_date=publication,
            effective_from=effective,
            effective_until=until,
            rescinded_at=rescinded,
        ) is version.is_valid_on(as_of)
