from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError

from apps.api.tests.conftest import reset_database
from korpus.application.corpus_snapshot import version_evidence_digest
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    ReviewState,
)
from korpus.infrastructure import review_transitions
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.schema import spans, versions

POSTGRES_URL = os.getenv("KORPUS_POSTGRES_TEST_URL")
pytestmark = pytest.mark.postgres


@pytest.mark.skipif(not POSTGRES_URL, reason="KORPUS_POSTGRES_TEST_URL is not configured")
def test_postgres_approval_seal_serializes_concurrent_span_insert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A phantom span cannot cross the exact `seal -> approve` boundary.

    The barrier is inside the approval transaction after the evidence rows have been
    sealed. No sleep creates the race: approval is held at that exact call boundary and
    a competing INSERT gets a bounded PostgreSQL lock timeout. Existing-row locks alone
    cannot stop this control; it specifically proves the parent-version lock protocol.
    """
    reset_database()
    repository = SqlRepository(
        POSTGRES_URL,
        "postgres-temporal-concurrency-key",
        audit_anchor_path=tmp_path / "postgres-temporal-anchor.json",
    )
    repository.initialize(create_schema=False)
    actor = Identity(
        subject="postgres-temporal-admin",
        roles=frozenset({"admin", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )
    document = DocumentRecord(
        canonical_title="PostgreSQL temporal sealing fixture",
        corpus_id="public",
        issuer="Integration Authority",
        jurisdiction="UA",
        document_type="order",
        access_tier=AccessTier.PUBLIC,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1",
        source_hash="d" * 64,
        object_key="integration/temporal-seal",
        mime_type="text/plain",
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.QUARANTINED,
        publication_date=date(2020, 1, 1),
        is_current=False,
    )
    span = EvidenceSpanRecord(
        version_id=version.id,
        ordinal=0,
        text="POSTGRES-SEAL-RACE evidence must not change across approval.",
    )
    repository.create_document_bundle(
        actor,
        document,
        version,
        [span],
        {"integration": "postgres", "control": "approval-seal-race"},
    )

    sealed = Event()
    release_approval = Event()
    original_seal = review_transitions._seal_evidence_digest

    def blocking_seal(connection, version_id):
        digest = original_seal(connection, version_id)
        sealed.set()
        if not release_approval.wait(timeout=5):
            raise TimeoutError("approval race barrier was not released")
        return digest

    monkeypatch.setattr(review_transitions, "_seal_evidence_digest", blocking_seal)

    injected_text = "phantom evidence inserted after the approval seal"
    injected_hash = hashlib.sha256(injected_text.encode("utf-8")).hexdigest()
    injected_id = str(uuid4())
    injected_values = {
        "id": injected_id,
        "version_id": str(version.id),
        "ordinal": 1,
        "page": None,
        "section": None,
        "text": injected_text,
        "text_hash": injected_hash,
        "created_at": datetime.now(UTC),
    }

    with ThreadPoolExecutor(max_workers=1) as executor:
        approval = executor.submit(
            repository.transition_version,
            actor,
            version.id,
            ReviewState.QUARANTINED,
            ReviewState.APPROVED,
            "deterministic PostgreSQL seal/insert race",
        )
        assert sealed.wait(timeout=5), "approval did not reach the post-seal barrier"
        try:
            with pytest.raises(DBAPIError), repository.engine.begin() as connection:
                repository._apply_postgres_identity(connection, actor)
                connection.execute(text("SET LOCAL lock_timeout = '250ms'"))
                connection.execute(insert(spans).values(**injected_values))
        finally:
            release_approval.set()
        approved = approval.result(timeout=5)

    assert approved.review_state is ReviewState.APPROVED

    # Once approval commits, the same phantom insert is rejected by the immutable-
    # evidence trigger rather than merely blocked by the transition lock.
    with pytest.raises(DBAPIError), repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, actor)
        connection.execute(insert(spans).values(**injected_values))

    with repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, actor)
        stored_digest = connection.execute(
            select(versions.c.evidence_digest).where(versions.c.id == str(version.id))
        ).scalar_one()
        row = connection.execute(
            select(
                spans.c.id,
                spans.c.ordinal,
                spans.c.page,
                spans.c.section,
                spans.c.text,
                spans.c.text_hash,
            ).where(spans.c.version_id == str(version.id))
        ).mappings().one()

    expected_digest = version_evidence_digest(
        [
            (
                str(row["id"]),
                int(row["ordinal"]),
                None if row["page"] is None else int(row["page"]),
                None if row["section"] is None else str(row["section"]),
                str(row["text"]),
                str(row["text_hash"]),
            )
        ]
    )
    assert stored_digest == expected_digest
    assert row["id"] == str(span.id)
    repository.close()
