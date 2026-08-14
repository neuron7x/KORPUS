from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select, text, update

from apps.api.tests.conftest import reset_database
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
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.rls_repository import RlsBoundSqlRepository
from korpus.infrastructure.schema import documents

POSTGRES_URL = os.getenv("KORPUS_POSTGRES_TEST_URL")
REVIEW_URL = os.getenv("KORPUS_REVIEW_DATABASE_URL")
AUTHZ_URL = os.getenv("KORPUS_AUTHZ_DATABASE_URL")
pytestmark = pytest.mark.postgres


def _admin() -> Identity:
    return Identity(
        subject="rls-boundary-admin",
        roles=frozenset({"admin", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public", "secret"}),
        compartments=frozenset({"alpha"}),
    )


def _low() -> Identity:
    return Identity(
        subject="rls-boundary-low",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
        compartments=frozenset(),
    )


def _create_document(
    repository: SqlRepository,
    *,
    corpus_id: str = "public",
    access_tier: AccessTier = AccessTier.PUBLIC,
    classification: Classification = Classification.PUBLIC,
    compartments: frozenset[str] = frozenset(),
) -> DocumentRecord:
    document = DocumentRecord(
        canonical_title="RLS claim forgery control",
        corpus_id=corpus_id,
        issuer="Integration Authority",
        jurisdiction="UA",
        document_type="order",
        access_tier=access_tier,
        classification=classification,
        compartments=compartments,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1",
        source_hash="a" * 64,
        object_key=f"rls-claim-forgery/{document.id}",
        mime_type="text/plain",
        publication_date=date(2026, 1, 1),
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.QUARANTINED,
    )
    span = EvidenceSpanRecord(
        version_id=version.id,
        ordinal=0,
        text="RLS claims must not be forgeable by SQL available to the application login.",
    )
    repository.create_document_bundle(
        _admin(), document, version, [span], {"control": "rls-claim-forgery"}
    )
    return document


def _repository(tmp_path: Path) -> RlsBoundSqlRepository:
    assert POSTGRES_URL is not None and REVIEW_URL is not None and AUTHZ_URL is not None
    repository = RlsBoundSqlRepository(
        POSTGRES_URL,
        "rls-claim-forgery-test-key",
        audit_anchor_path=tmp_path / "rls-claim-forgery-anchor.json",
        review_database_url=REVIEW_URL,
        authz_database_url=AUTHZ_URL,
    )
    repository.initialize(create_schema=False)
    return repository


def _count(connection, document_id: str) -> int:
    return int(
        connection.execute(
            select(documents.c.id).where(documents.c.id == document_id)
        ).scalar_one_or_none()
        is not None
    )


@pytest.mark.skipif(
    not POSTGRES_URL or not REVIEW_URL or not AUTHZ_URL,
    reason="split PostgreSQL app/review/authz URLs are required",
)
@pytest.mark.parametrize(
    ("axis", "document_kwargs", "setting", "forged_value"),
    [
        (
            "clearance",
            {"access_tier": AccessTier.RESTRICTED},
            "korpus.clearance",
            str(int(AccessTier.RESTRICTED)),
        ),
        ("corpus", {"corpus_id": "secret"}, "korpus.corpora", "public,secret"),
        (
            "classification",
            {"classification": Classification.RESTRICTED},
            "korpus.classifications",
            f"{Classification.PUBLIC.value},{Classification.RESTRICTED.value}",
        ),
        (
            "compartment",
            {"compartments": frozenset({"alpha"})},
            "korpus.compartments",
            "alpha",
        ),
    ],
)
def test_app_sql_cannot_self_increase_rls_visibility_claim(
    tmp_path: Path,
    axis: str,
    document_kwargs: dict[str, object],
    setting: str,
    forged_value: str,
) -> None:
    del axis
    reset_database()
    repository = _repository(tmp_path)
    document = _create_document(repository, **document_kwargs)
    low = _low()
    try:
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, low)
            assert _count(connection, str(document.id)) == 0
            connection.execute(
                text("SELECT set_config(:setting, :value, true)"),
                {"setting": setting, "value": forged_value},
            )
            assert _count(connection, str(document.id)) == 0
    finally:
        repository.close()


@pytest.mark.skipif(
    not POSTGRES_URL or not REVIEW_URL or not AUTHZ_URL,
    reason="split PostgreSQL app/review/authz URLs are required",
)
def test_app_sql_cannot_self_grant_rls_writer_role(tmp_path: Path) -> None:
    reset_database()
    repository = _repository(tmp_path)
    document = _create_document(repository)
    low = _low()
    try:
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, low)
            baseline = connection.execute(
                update(documents)
                .where(documents.c.id == str(document.id))
                .values(canonical_title="unauthorized baseline")
            )
            assert baseline.rowcount == 0

        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, low)
            connection.execute(text("SELECT set_config('korpus.roles', 'admin', true)"))
            forged = connection.execute(
                update(documents)
                .where(documents.c.id == str(document.id))
                .values(canonical_title="forged writer")
            )
            assert forged.rowcount == 0
    finally:
        repository.close()