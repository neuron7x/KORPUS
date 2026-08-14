from __future__ import annotations

import os
from datetime import date
from pathlib import Path

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
from korpus.infrastructure.schema import versions
from korpus.infrastructure.secure_repository import RlsBoundSqlRepository

POSTGRES_URL = os.getenv("KORPUS_POSTGRES_TEST_URL")
REVIEW_URL = os.getenv("KORPUS_REVIEW_DATABASE_URL")
IDENTITY_URL = os.getenv("RLS_IDENTITY_DATABASE_URL")
pytestmark = pytest.mark.postgres


def _actor() -> Identity:
    return Identity(
        subject="approval-boundary-admin",
        roles=frozenset({"admin", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )


def _bundle() -> tuple[DocumentRecord, DocumentVersionRecord, EvidenceSpanRecord]:
    document = DocumentRecord(
        canonical_title="Approval provenance control",
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
        object_key="approval-boundary/1",
        mime_type="text/plain",
        publication_date=date(2026, 1, 1),
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.QUARANTINED,
    )
    span = EvidenceSpanRecord(
        version_id=version.id,
        ordinal=0,
        text="Approval provenance must be derived from this exact persisted evidence.",
    )
    return document, version, span


@pytest.mark.skipif(
    not POSTGRES_URL or not REVIEW_URL or not IDENTITY_URL,
    reason="split PostgreSQL app/review/identity URLs are required",
)
def test_app_role_cannot_manufacture_approved_state(tmp_path: Path) -> None:
    reset_database()
    assert POSTGRES_URL and REVIEW_URL and IDENTITY_URL
    repository = RlsBoundSqlRepository(
        POSTGRES_URL,
        "approval-provenance-test-key",
        audit_anchor_path=tmp_path / "approval-provenance-anchor.json",
        review_database_url=REVIEW_URL,
        rls_identity_database_url=IDENTITY_URL,
    )
    repository.initialize(create_schema=False)
    actor = _actor()
    document, version, span = _bundle()
    repository.create_document_bundle(
        actor,
        document,
        version,
        [span],
        {"control": "approval-provenance"},
    )

    try:
        with repository.engine.connect() as connection:
            app_role = connection.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            ).one()
            grants = connection.execute(
                text(
                    "SELECT "
                    "has_column_privilege(current_user, 'document_versions', "
                    "'review_state', 'UPDATE') AS review_state_update, "
                    "has_column_privilege(current_user, 'document_versions', "
                    "'evidence_digest', 'UPDATE') AS evidence_digest_update, "
                    "has_column_privilege(current_user, 'document_versions', "
                    "'rescinded_at', 'UPDATE') AS rescinded_at_update"
                )
            ).one()
        assert repository.review_engine is not None
        with repository.review_engine.connect() as connection:
            review_role = connection.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            ).one()
            review_can_update = connection.execute(
                text(
                    "SELECT has_column_privilege(current_user, 'document_versions', "
                    "'review_state', 'UPDATE')"
                )
            ).scalar_one()

        assert app_role.current_user == "korpus_app"
        assert app_role.rolsuper is False and app_role.rolbypassrls is False
        assert grants.review_state_update is False
        assert grants.evidence_digest_update is False
        assert grants.rescinded_at_update is True
        assert review_role.current_user == "korpus_review"
        assert review_role.rolsuper is False and review_role.rolbypassrls is False
        assert review_can_update is True

        with pytest.raises(DBAPIError), repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, actor)
            connection.execute(
                update(versions)
                .where(versions.c.id == str(version.id))
                .values(review_state=ReviewState.APPROVED.value, evidence_digest="f" * 64)
            )

        forged = DocumentVersionRecord(
            document_id=document.id,
            revision="2",
            source_hash="e" * 64,
            object_key="approval-boundary/forged",
            mime_type="text/plain",
            publication_date=date(2026, 1, 1),
            authority=AuthorityClass.OFFICIAL_UA,
            review_state=ReviewState.APPROVED,
        )
        forged_values = repository._version_values(forged)
        forged_values["evidence_digest"] = "f" * 64
        with pytest.raises(DBAPIError, match="application role cannot insert review-controlled state"):
            with repository.engine.begin() as connection:
                repository._apply_postgres_identity(connection, actor)
                connection.execute(insert(versions).values(**forged_values))

        with pytest.raises(DBAPIError), repository.engine.begin() as connection:
            connection.execute(text("SET ROLE korpus_review"))

        repository.transition_version(
            actor,
            version.id,
            ReviewState.QUARANTINED,
            ReviewState.APPROVED,
            "authorized approval through split review identity",
        )
        expected_digest = version_evidence_digest(
            [(str(span.id), span.ordinal, span.page, span.section, span.text, span.text_hash)]
        )
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, actor)
            state, digest = connection.execute(
                select(versions.c.review_state, versions.c.evidence_digest).where(
                    versions.c.id == str(version.id)
                )
            ).one()
        assert state == ReviewState.APPROVED.value
        assert digest == expected_digest
    finally:
        repository.close()
