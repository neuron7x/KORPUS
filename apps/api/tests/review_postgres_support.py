"""Disposable PostgreSQL review fixtures; all document/review operations use runtime roles."""

from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.policy import PolicyEngine
from korpus.composition import build_ingestion_service
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    DocumentCreate,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    ReviewState,
    ReviewTransition,
)
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.infrastructure.rls_repository import RlsBoundSqlRepository
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from apps.api.tests import conftest


def actor(subject: str, role: str, **changes) -> Identity:
    values = dict(
        subject=subject,
        roles=frozenset({role}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
        compartments=frozenset({"archive"}),
    )
    values.update(changes)
    return Identity(**values)


CURATOR = actor("review-fixture-owner", "curator", corpora=frozenset({"public", "hidden"}))
METADATA = actor("review-fixture-metadata", "curator")
CONTENT = actor("review-fixture-content", "reviewer")
APPROVER = actor("review-fixture-approver", "reviewer")


@dataclass
class ReviewPostgres:
    repository: RlsBoundSqlRepository
    service: IngestionService
    review_login: str

    def seed(self, **changes) -> tuple[DocumentRecord, DocumentVersionRecord]:
        description = DocumentCreate(
            canonical_title="Archive label", issuer="Synthetic fixture", **changes
        )
        document = DocumentRecord(**description.model_dump())
        payload = b"The archive label is blue.\n"
        version = DocumentVersionRecord(
            document_id=document.id,
            revision="1",
            source_hash=hashlib.sha256(payload).hexdigest(),
            object_key=f"synthetic/{uuid4()}",
            mime_type="text/plain",
            authority=AuthorityClass.ANALYTICAL,
            publication_date=date(2020, 1, 1),
        )
        span = EvidenceSpanRecord(version_id=version.id, ordinal=0, text=payload.decode())
        self.repository.create_document_bundle(
            CURATOR, document, version, [span], {"fixture": "review-scope"}
        )
        return document, version

    def transition(self, identity: Identity, version_id, target: ReviewState, **changes):
        return self.service.transition(
            identity,
            version_id,
            ReviewTransition(target=target, note="Synthetic review acceptance", **changes),
        )


@contextmanager
def _review_url(owner_url: str, configured: str, custom: bool) -> Iterator[str]:
    if not custom:
        yield configured
        return
    name = "korpus_review_fixture_" + uuid4().hex
    password = secrets.token_hex(24)
    base = make_url(configured)
    owner = create_engine(owner_url, hide_parameters=True)
    try:
        with owner.begin() as connection:
            # Secret values remain bound parameters; CREATE ROLE's SQL text contains none.
            connection.execute(
                text(
                    "SELECT set_config('korpus.fixture_role', :name, true), "
                    "set_config('korpus.fixture_secret', :password, true)"
                ),
                {"name": name, "password": password},
            )
            connection.execute(
                text("""
                DO $$ BEGIN EXECUTE format(
                  'CREATE ROLE %I LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
                  current_setting('korpus.fixture_role'), current_setting('korpus.fixture_secret')
                ); END $$
            """)
            )
            source = '"' + (base.username or "").replace('"', '""') + '"'
            connection.exec_driver_sql(f'GRANT {source} TO "{name}"')
        yield base.set(username=name, password=password).render_as_string(hide_password=False)
    finally:
        with owner.begin() as connection:
            connection.exec_driver_sql(f'DROP ROLE IF EXISTS "{name}"')
        owner.dispose()


@pytest.fixture
def review_postgres(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[ReviewPostgres]:
    app_url = os.getenv("KORPUS_TEST_DATABASE_URL")
    if not app_url:
        pytest.skip("native review acceptance requires the disposable PostgreSQL suite")
    owner_url = os.getenv("KORPUS_TEST_DATABASE_ADMIN_URL")
    authz_url = os.getenv("KORPUS_AUTHZ_DATABASE_URL")
    review_url = os.getenv("KORPUS_REVIEW_DATABASE_URL")
    assert owner_url and authz_url and review_url, (
        "all provisioned PostgreSQL identities are required"
    )
    if app_url != conftest.POSTGRES_SUITE_URL or owner_url != conftest.POSTGRES_ADMIN_URL:
        pytest.fail("suite reset configuration changed after conftest loaded")
    targets = [make_url(url) for url in (app_url, owner_url, authz_url, review_url)]
    app = targets[0]
    assert app.database in {"korpus_suite", "korpus_coverage", "korpus_test"}, (
        "non-disposable database refused"
    )
    assert (
        all(target.username for target in targets)
        and len({target.username for target in targets}) == 4
    )
    assert all(
        target.get_backend_name() == "postgresql"
        and (target.host, target.port, target.database) == (app.host, app.port, app.database)
        for target in targets
    ), "identities must target the same isolated database"
    conftest.reset_database()
    try:
        with _review_url(
            owner_url, review_url, getattr(request, "param", "configured") == "custom"
        ) as selected:
            repository = RlsBoundSqlRepository(
                app_url,
                "review-scope-audit-key",
                authz_database_url=authz_url,
                review_database_url=selected,
                audit_anchor_path=tmp_path / "anchor.json",
                pool_size=1,
                max_overflow=0,
            )
            try:
                repository.initialize(create_schema=False)
                assert repository.review_engine is not None
                for engine, login in (
                    (repository.engine, app.username),
                    (repository.review_engine, make_url(selected).username),
                ):
                    with engine.connect() as connection:
                        row = connection.execute(
                            text(
                                "SELECT current_user, session_user, rolsuper, rolbypassrls "
                                "FROM pg_roles WHERE rolname = current_user"
                            )
                        ).one()
                    assert row.current_user == row.session_user == login
                    assert row.rolsuper is False and row.rolbypassrls is False
                service = build_ingestion_service(
                    repository,
                    LocalObjectStore(tmp_path / "objects"),
                    PolicyEngine(),
                    ExtractionSettings(ocr_enabled=False, ocr_languages="ukr"),
                    review_separation_required=True,
                )
                yield ReviewPostgres(repository, service, make_url(selected).username or "")
            finally:
                repository.close()
    finally:
        conftest.reset_database()
