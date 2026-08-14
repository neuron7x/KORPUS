from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text, update
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
@pytest.mark.parametrize("mutation_kind", ["insert", "update"])
def test_postgres_approval_seal_serializes_concurrent_evidence_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation_kind: str
) -> None:
    """No evidence writer can cross the exact `seal -> approve` boundary.

    INSERT is the phantom control: existing-row locks cannot stop it, so it proves the
    parent-version protocol. UPDATE also exercises the lock order that can deadlock if
    approval takes parent->span locks while DML takes span->parent. No sleeps create the
    interleaving; an Event holds approval exactly after sealing and PostgreSQL bounds the
    competing lock wait.
    """
    reset_database()
    repository = SqlRepository(
        POSTGRES_URL,
        "postgres-temporal-concurrency-key",
        audit_anchor_path=tmp_path / f"postgres-temporal-anchor-{mutation_kind}.json",
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
        {"integration": "postgres", "control": f"approval-seal-{mutation_kind}-race"},
    )

    sealed = Event()
    release_approval = Event()
    original_seal = review_transitions.seal_evidence_digest

    def blocking_seal(connection, version_id):
        digest = original_seal(connection, version_id)
        sealed.set()
        if not release_approval.wait(timeout=5):
            raise TimeoutError("approval race barrier was not released")
        return digest

    monkeypatch.setattr(review_transitions, "seal_evidence_digest", blocking_seal)

    changed_text = f"{span.text} tampered during approval"
    changed_hash = hashlib.sha256(changed_text.encode("utf-8")).hexdigest()
    phantom_text = "phantom evidence inserted after the approval seal"
    injected_values = {
        "id": str(uuid4()),
        "version_id": str(version.id),
        "ordinal": 1,
        "page": None,
        "section": None,
        "text": phantom_text,
        "text_hash": hashlib.sha256(phantom_text.encode("utf-8")).hexdigest(),
        "created_at": datetime.now(UTC),
    }

    def mutate(connection) -> None:
        if mutation_kind == "insert":
            connection.execute(insert(spans).values(**injected_values))
            return
        connection.execute(
            update(spans)
            .where(spans.c.id == str(span.id))
            .values(text=changed_text, text_hash=changed_hash)
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        approval = executor.submit(
            repository.transition_version,
            actor,
            version.id,
            ReviewState.QUARANTINED,
            ReviewState.APPROVED,
            f"deterministic PostgreSQL seal/{mutation_kind} race",
        )
        assert sealed.wait(timeout=5), "approval did not reach the post-seal barrier"
        try:
            with pytest.raises(DBAPIError), repository.engine.begin() as connection:
                repository._apply_postgres_identity(connection, actor)
                connection.execute(text("SET LOCAL lock_timeout = '250ms'"))
                mutate(connection)
        finally:
            release_approval.set()
        approved = approval.result(timeout=5)

    assert approved.review_state is ReviewState.APPROVED

    # After approval, the same DML must be rejected because evidence is immutable, not
    # merely because the approval transaction happened to hold a lock.
    with pytest.raises(DBAPIError), repository.engine.begin() as connection:
        repository._apply_postgres_identity(connection, actor)
        mutate(connection)

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
    assert row["text"] == span.text
    repository.close()
