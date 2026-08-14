from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError

from apps.api.tests.conftest import reset_database
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.schema import corpus_state_epoch

POSTGRES_URL = os.getenv("KORPUS_POSTGRES_TEST_URL")
pytestmark = pytest.mark.postgres


@pytest.mark.skipif(not POSTGRES_URL, reason="KORPUS_POSTGRES_TEST_URL is not configured")
def test_postgres_application_role_cannot_forge_corpus_state_epoch(tmp_path: Path) -> None:
    """The monotonic epoch is observable to the app but not writable by it."""
    reset_database()
    repository = SqlRepository(
        POSTGRES_URL,
        "postgres-temporal-privilege-key",
        audit_anchor_path=tmp_path / "postgres-temporal-privilege-anchor.json",
    )
    repository.initialize(create_schema=False)
    actor = Identity(
        subject="postgres-temporal-admin",
        roles=frozenset({"admin", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )

    try:
        with pytest.raises(DBAPIError), repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, actor)
            connection.execute(
                update(corpus_state_epoch)
                .where(corpus_state_epoch.c.singleton_id == 1)
                .values(epoch=corpus_state_epoch.c.epoch + 1000)
            )
    finally:
        repository.close()
