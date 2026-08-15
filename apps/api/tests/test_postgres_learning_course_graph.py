from __future__ import annotations

import hashlib
import os
from datetime import UTC, date, datetime

import pytest
from korpus.domain.learning import (
    Course,
    CourseModule,
    CourseVersion,
    LearningObjective,
    Lesson,
    LessonBlock,
    LessonBlockKind,
    SourceBinding,
)
from korpus.infrastructure.learning_repository import SqlLearningRepository
from korpus.infrastructure.learning_schema import (
    learning_courses,
    learning_lessons,
    learning_publications,
)
from korpus.infrastructure.schema import documents, spans, versions
from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.exc import DBAPIError

POSTGRES_ADMIN_URL = os.getenv("KORPUS_TEST_DATABASE_ADMIN_URL")
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.integration,
    pytest.mark.skipif(not POSTGRES_ADMIN_URL, reason="PostgreSQL admin URL not configured"),
]

DOC_ID = "00000000-0000-0000-0000-000000000201"
VERSION_ID = "00000000-0000-0000-0000-000000000202"
SPAN_ID = "00000000-0000-0000-0000-000000000203"
SOURCE_TEXT = "Verified PostgreSQL material"


def _frame(hasher: object, value: str) -> None:
    encoded = value.encode("utf-8")
    hasher.update(len(encoded).to_bytes(8, "big"))  # type: ignore[attr-defined]
    hasher.update(encoded)  # type: ignore[attr-defined]


def _sealed_evidence_digest(text_hash: str) -> str:
    digest = hashlib.sha256()
    digest.update(b"korpus-version-evidence-v1\0")
    for value in (SPAN_ID, "0", "1:1", "1:s1", text_hash):
        _frame(digest, value)
    return digest.hexdigest()


def _seed_source(engine) -> None:
    stamp = datetime(2026, 8, 15, 8, 0, tzinfo=UTC)
    text_hash = hashlib.sha256(SOURCE_TEXT.encode("utf-8")).hexdigest()
    evidence_digest = _sealed_evidence_digest(text_hash)
    with engine.begin() as connection:
        connection.execute(delete(learning_courses).where(learning_courses.c.id == "course-pg"))
        connection.execute(delete(spans).where(spans.c.id == SPAN_ID))
        connection.execute(delete(versions).where(versions.c.id == VERSION_ID))
        connection.execute(delete(documents).where(documents.c.id == DOC_ID))
        connection.execute(
            insert(documents).values(
                id=DOC_ID,
                canonical_title="PostgreSQL learning source",
                corpus_id="training",
                issuer="test",
                jurisdiction="UA",
                document_type="manual",
                access_tier=0,
                classification="public",
                compartments_json="[]",
                created_at=stamp,
            )
        )
        # Evidence must exist before approval seals the parent version. A non-null
        # evidence_digest makes evidence_spans immutable by the existing corpus guard.
        connection.execute(
            insert(versions).values(
                id=VERSION_ID,
                document_id=DOC_ID,
                revision="1",
                publication_identifier=None,
                source_uri=None,
                source_hash="d" * 64,
                evidence_digest=None,
                object_key="objects/pg-source.pdf",
                mime_type="application/pdf",
                publication_date=date(2026, 8, 1),
                effective_from=date(2026, 8, 1),
                effective_until=None,
                rescinded_at=None,
                authority="approved_training",
                source_key_id=None,
                source_signature_b64=None,
                content_fingerprint="1" * 16,
                near_duplicate_of_version_id=None,
                near_duplicate_similarity=None,
                near_duplicate_acknowledged_by=None,
                extraction_text_chars=100,
                extraction_alnum_ratio=1.0,
                extraction_replacement_ratio=0.0,
                extraction_quality_flags_json="[]",
                extraction_quality_acknowledged_by=None,
                review_state="quarantined",
                supersedes_version_id=None,
                state_version=0,
                metadata_reviewed_by=None,
                metadata_reviewer_credential_id=None,
                content_reviewed_by=None,
                content_reviewer_credential_id=None,
                approved_at=None,
                approved_by=None,
                approver_credential_id=None,
                is_current=False,
                created_at=stamp,
            )
        )
        connection.execute(
            insert(spans).values(
                id=SPAN_ID,
                version_id=VERSION_ID,
                ordinal=0,
                page=1,
                section="s1",
                text=SOURCE_TEXT,
                text_hash=text_hash,
                created_at=stamp,
            )
        )
        connection.execute(
            update(versions)
            .where(versions.c.id == VERSION_ID)
            .values(
                evidence_digest=evidence_digest,
                review_state="approved",
                state_version=3,
                metadata_reviewed_by="reviewer",
                content_reviewed_by="reviewer",
                approved_at=stamp,
                approved_by="reviewer",
                is_current=True,
            )
        )


def _course_version(version_id: str, revision: str) -> CourseVersion:
    binding = SourceBinding(
        id="source-pg",
        document_id=DOC_ID,
        version_id=VERSION_ID,
        evidence_span_ids=frozenset({SPAN_ID}),
    )
    return CourseVersion(
        id=version_id,
        course_id="course-pg",
        revision=revision,
        modules=(
            CourseModule(
                id="module-pg",
                ordinal=0,
                title="PostgreSQL module",
                lessons=(
                    Lesson(
                        id="lesson-pg",
                        ordinal=0,
                        title="PostgreSQL lesson",
                        objectives=(
                            LearningObjective(id="objective-pg", statement="Verify persistence"),
                        ),
                        source_bindings=(binding,),
                        blocks=(
                            LessonBlock(
                                id="block-pg",
                                ordinal=0,
                                kind=LessonBlockKind.TEXT,
                                title="Verified material",
                                source_binding_ids=frozenset({binding.id}),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def test_postgres_published_graph_is_immutable_and_source_rescind_invalidates() -> None:
    assert POSTGRES_ADMIN_URL is not None
    engine = create_engine(POSTGRES_ADMIN_URL, future=True)
    try:
        _seed_source(engine)
        repository = SqlLearningRepository(engine)
        repository.save_course(
            Course(id="course-pg", specialty_id="training", title="PostgreSQL course")
        )
        repository.save_version(
            _course_version("course-pg-v1", "1"), as_of=date(2026, 8, 15)
        )
        repository.save_version(
            _course_version("course-pg-v2", "2"), as_of=date(2026, 8, 15)
        )
        repository.publish(
            "course-pg-v1",
            reviewed_by="postgres-sme",
            reviewed_at=datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
            as_of=date(2026, 8, 15),
        )

        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(
                update(learning_lessons)
                .where(learning_lessons.c.course_version_id == "course-pg-v1")
                .values(title="tampered")
            )

        with engine.begin() as connection:
            connection.execute(
                update(versions)
                .where(versions.c.id == VERSION_ID)
                .values(rescinded_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC))
            )
            invalidated = connection.execute(
                select(learning_publications.c.state).where(
                    learning_publications.c.course_version_id == "course-pg-v1"
                )
            ).scalar_one()
        assert invalidated == "invalidated"

        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(
                update(learning_publications)
                .where(learning_publications.c.course_version_id == "course-pg-v2")
                .values(
                    state="published",
                    reviewed_at=datetime(2026, 8, 15, 10, 1, tzinfo=UTC),
                    reviewed_by="postgres-sme",
                    updated_at=datetime(2026, 8, 15, 10, 1, tzinfo=UTC),
                )
            )
    finally:
        engine.dispose()
