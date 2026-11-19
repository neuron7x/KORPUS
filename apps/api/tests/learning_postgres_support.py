"""Public educational fixtures for migrated PostgreSQL learning acceptance.

Only fixture setup/reset uses the owner. Every graph operation and observation
uses the configured application login; no SQLite substitute can satisfy these tests.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from korpus.domain.learning import (
    Course,
    CourseModule,
    CourseVersion,
    LearningObjective,
    Lesson,
    LessonBlock,
    LessonBlockKind,
    Prerequisite,
    SourceBinding,
)
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    ReviewState,
)
from korpus.infrastructure import row_mapping
from korpus.infrastructure.evidence_sealing import seal_evidence_digest
from korpus.infrastructure.learning_repository import SqlLearningRepository
from korpus.infrastructure.learning_schema import LEARNING_TABLES
from korpus.infrastructure.schema import SCHEMA_REVISION, documents, spans, versions
from sqlalchemy import create_engine, insert, text, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

from apps.api.tests.conftest import reset_database

SOURCE = (
    UUID("10000000-0000-0000-0000-000000000001"),
    UUID("20000000-0000-0000-0000-000000000001"),
    UUID("30000000-0000-0000-0000-000000000001"),
)
OTHER_SOURCE = (
    UUID("10000000-0000-0000-0000-000000000002"),
    UUID("20000000-0000-0000-0000-000000000002"),
    UUID("30000000-0000-0000-0000-000000000002"),
)
MISSING_ID = "40000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class LearningPostgres:
    app: Engine
    fixture_owner: Engine
    today: date
    learning: SqlLearningRepository


def course_graph(
    *, revision: str = "1", binding_changes: dict[str, object] | None = None
) -> CourseVersion:
    binding = SourceBinding(
        id="source",
        document_id=str(SOURCE[0]),
        version_id=str(SOURCE[1]),
        evidence_span_ids=frozenset({str(SOURCE[2])}),
    ).model_copy(update=binding_changes or {})
    alternate = SourceBinding(
        id="alternate-source",
        document_id=str(OTHER_SOURCE[0]),
        version_id=str(OTHER_SOURCE[1]),
        evidence_span_ids=frozenset({str(OTHER_SOURCE[2])}),
    )
    lessons = tuple(
        Lesson(
            id=name,
            ordinal=ordinal,
            title=f"Public library {name}",
            objectives=(LearningObjective(id=f"{name}-objective", statement="Identify a source"),),
            source_bindings=(alternate, binding),
            blocks=(
                LessonBlock(
                    id="reading",
                    ordinal=0,
                    kind=LessonBlockKind.TEXT,
                    title="Read the source reference",
                    source_binding_ids=frozenset({binding.id}),
                ),
            ),
            prerequisites=() if ordinal == 0 else (Prerequisite(lesson_id="catalog"),),
        )
        for ordinal, name in enumerate(("catalog", "citations"))
    )
    return CourseVersion(
        id=f"library-v{revision}",
        course_id="library",
        revision=revision,
        modules=(CourseModule(id="basics", ordinal=0, title="Library basics", lessons=lessons),),
    )


def _seed_source(owner: Engine, identity: tuple[UUID, UUID, UUID], today: date) -> None:
    source_text = "A public library catalog groups books by subject."
    document = DocumentRecord(
        id=identity[0],
        canonical_title="Public library reference",
        corpus_id="public",
        issuer="Educational fixture",
        jurisdiction="GLOBAL",
        document_type="reference",
        access_tier=AccessTier.PUBLIC,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        id=identity[1],
        document_id=document.id,
        revision="1",
        source_hash=hashlib.sha256(source_text.encode()).hexdigest(),
        object_key=f"public-learning-fixture/{identity[1]}",
        mime_type="text/plain",
        publication_date=today - timedelta(days=30),
        effective_from=today - timedelta(days=30),
        effective_until=today + timedelta(days=30),
        authority=AuthorityClass.APPROVED_TRAINING,
        review_state=ReviewState.QUARANTINED,
    )
    span = EvidenceSpanRecord(id=identity[2], version_id=version.id, ordinal=0, text=source_text)
    with owner.begin() as connection:
        connection.execute(insert(documents).values(**row_mapping.document_values(document)))
        connection.execute(insert(versions).values(**row_mapping.version_values(version)))
        connection.execute(insert(spans).values(**row_mapping.span_values(span)))
        connection.execute(
            update(versions)
            .where(versions.c.id == str(version.id))
            .values(
                review_state=ReviewState.APPROVED.value,
                approved_at=datetime.now(UTC),
                approved_by="public-fixture-reviewer",
                evidence_digest=seal_evidence_digest(connection, version.id),
                is_current=True,
            )
        )


@pytest.fixture
def learning_postgres(request: pytest.FixtureRequest) -> Iterator[LearningPostgres]:
    app_url = os.getenv("KORPUS_TEST_DATABASE_URL")
    if not app_url:
        pytest.skip("actual PostgreSQL learning acceptance requires KORPUS_TEST_DATABASE_URL")
    owner_url = os.getenv("KORPUS_TEST_DATABASE_ADMIN_URL")
    assert owner_url, "PostgreSQL acceptance requires a separate fixture-owner URL"
    app_target, owner_target = make_url(app_url), make_url(owner_url)
    assert app_target.get_backend_name() == owner_target.get_backend_name() == "postgresql"
    assert (app_target.host, app_target.port, app_target.database) == (
        owner_target.host,
        owner_target.port,
        owner_target.database,
    ), "application and fixture owner must target the same isolated database"
    assert app_target.username != owner_target.username
    reset_database()
    app = create_engine(app_url)
    owner = create_engine(owner_url)
    try:
        with app.connect() as connection:
            role = connection.execute(
                text(
                    "SELECT current_user AS app_role, session_user AS login, "
                    "rolsuper, rolbypassrls, CURRENT_DATE AS today, "
                    "current_setting('server_version_num')::integer AS server_version "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
            expected_role = os.getenv("KORPUS_POSTGRES_APP_ROLE", "korpus_app")
            assert role.app_role == role.login == expected_role
            assert role.rolsuper is False and role.rolbypassrls is False
            assert role.server_version // 10000 == 17
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == SCHEMA_REVISION
            names = [table.name for table in LEARNING_TABLES]
            owners = connection.execute(
                text(
                    "SELECT c.relname, pg_has_role(current_user, c.relowner, 'USAGE') "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname = ANY(:names)"
                ),
                {"names": names},
            ).all()
            assert {row[0] for row in owners} == set(names)
            assert all(not row[1] for row in owners), owners
            # Refusals below must come from invariants, not absent DML grants.
            for table in names:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert connection.execute(
                        text("SELECT has_table_privilege(current_user, :table, :privilege)"),
                        {"table": f"public.{table}", "privilege": privilege},
                    ).scalar_one(), (table, privilege)
        request.node.user_properties.extend(
            (
                ("postgres_server_version_num", role.server_version),
                ("application_role", role.app_role),
                ("application_is_superuser", False),
                ("application_bypasses_rls", False),
                ("application_inherits_table_owner", False),
                ("migration_revision", revision),
            )
        )
        _seed_source(owner, SOURCE, role.today)
        _seed_source(owner, OTHER_SOURCE, role.today)
        learning = SqlLearningRepository(app)
        learning.create_course(Course(id="library", specialty_id="public", title="Library basics"))
        yield LearningPostgres(app, owner, role.today, learning)
    finally:
        app.dispose()
        owner.dispose()


def publish_sql(store: LearningPostgres, version_id: str) -> None:
    """Exercise the migrated SQL boundary without the Python publication validator."""
    with store.app.begin() as connection:
        result = connection.execute(
            text(
                "UPDATE learning_publications SET state = 'published', "
                "reviewed_by = 'public-course-reviewer', reviewed_at = CURRENT_TIMESTAMP, "
                "updated_at = CURRENT_TIMESTAMP WHERE course_version_id = :version"
            ),
            {"version": version_id},
        )
        assert result.rowcount == 1


def reject_sql(store: LearningPostgres, sql: str, *, sqlstate: str, message: str) -> None:
    with pytest.raises(DBAPIError, match=message) as failure, store.app.begin() as connection:
        connection.execute(text(sql))
    assert getattr(failure.value.orig, "sqlstate", None) == sqlstate


def set_source_fixture_state(store: LearningPostgres, **changes: object) -> None:
    """Prepare a canonical-source transition; this does not test owner authorization."""
    with store.fixture_owner.begin() as connection:
        result = connection.execute(
            update(versions).where(versions.c.id == str(SOURCE[1])).values(**changes)
        )
        assert result.rowcount == 1
