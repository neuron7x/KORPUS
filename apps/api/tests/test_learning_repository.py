from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, event, insert, update

from korpus.domain.learning import (
    Course,
    CourseModule,
    CoursePublicationState,
    CourseVersion,
    LearningObjective,
    Lesson,
    LessonBlock,
    LessonBlockKind,
    SourceBinding,
)
from korpus.infrastructure.learning_repository import LearningPublicationError, SqlLearningRepository
from korpus.infrastructure.learning_schema import learning_publications
from korpus.infrastructure.schema import documents, metadata, spans, versions

DOC_ID = "00000000-0000-0000-0000-000000000101"
VERSION_ID = "00000000-0000-0000-0000-000000000102"
SPAN_ID = "00000000-0000-0000-0000-000000000103"


def _engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'learning.db'}", future=True)

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine


def _seed_source(engine, *, effective_until: date | None = None) -> None:
    stamp = datetime(2026, 8, 15, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            insert(documents).values(
                id=DOC_ID,
                canonical_title="Approved source",
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
        connection.execute(
            insert(versions).values(
                id=VERSION_ID,
                document_id=DOC_ID,
                revision="1",
                publication_identifier=None,
                source_uri=None,
                source_hash="a" * 64,
                evidence_digest="b" * 64,
                object_key="objects/source.pdf",
                mime_type="application/pdf",
                publication_date=date(2026, 8, 1),
                effective_from=date(2026, 8, 1),
                effective_until=effective_until,
                rescinded_at=None,
                authority="approved_training",
                source_key_id=None,
                source_signature_b64=None,
                content_fingerprint="0" * 16,
                near_duplicate_of_version_id=None,
                near_duplicate_similarity=None,
                near_duplicate_acknowledged_by=None,
                extraction_text_chars=100,
                extraction_alnum_ratio=1.0,
                extraction_replacement_ratio=0.0,
                extraction_quality_flags_json="[]",
                extraction_quality_acknowledged_by=None,
                review_state="approved",
                supersedes_version_id=None,
                state_version=3,
                metadata_reviewed_by="reviewer",
                metadata_reviewer_credential_id=None,
                content_reviewed_by="reviewer",
                content_reviewer_credential_id=None,
                approved_at=stamp,
                approved_by="reviewer",
                approver_credential_id=None,
                is_current=True,
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
                text="Verified material",
                text_hash="c" * 64,
                created_at=stamp,
            )
        )


def _version(*, span_id: str = SPAN_ID) -> CourseVersion:
    binding = SourceBinding(
        id="source-a",
        document_id=DOC_ID,
        version_id=VERSION_ID,
        evidence_span_ids=frozenset({span_id}),
    )
    return CourseVersion(
        id="course-version-1",
        course_id="course-1",
        revision="1.0",
        modules=(
            CourseModule(
                id="module-1",
                ordinal=0,
                title="Module one",
                lessons=(
                    Lesson(
                        id="lesson-1",
                        ordinal=0,
                        title="Lesson one",
                        objectives=(
                            LearningObjective(id="objective-1", statement="Understand source"),
                        ),
                        source_bindings=(binding,),
                        blocks=(
                            LessonBlock(
                                id="block-1",
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


def test_course_version_round_trip_and_publish(tmp_path) -> None:
    engine = _engine(tmp_path)
    _seed_source(engine)
    repository = SqlLearningRepository(engine)
    repository.save_course(Course(id="course-1", specialty_id="training", title="Course one"))
    expected = _version()
    repository.save_version(expected, as_of=date(2026, 8, 15))

    assert repository.load_version(expected.id) == expected
    publication = repository.publish(
        expected.id,
        reviewed_by="sme-reviewer",
        reviewed_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
        as_of=date(2026, 8, 15),
    )
    assert publication.state is CoursePublicationState.PUBLISHED
    with engine.begin() as connection:
        state = connection.execute(
            learning_publications.select().where(
                learning_publications.c.course_version_id == expected.id
            )
        ).mappings().one()["state"]
    assert state == "published"
    engine.dispose()


def test_mismatched_evidence_span_fails_closed(tmp_path) -> None:
    engine = _engine(tmp_path)
    _seed_source(engine)
    repository = SqlLearningRepository(engine)
    repository.save_course(Course(id="course-1", specialty_id="training", title="Course one"))

    with pytest.raises(LearningPublicationError, match="evidence_span_mismatch"):
        repository.save_version(
            _version(span_id="00000000-0000-0000-0000-000000000999"),
            as_of=date(2026, 8, 15),
        )
    engine.dispose()


def test_rescinded_source_blocks_publication(tmp_path) -> None:
    engine = _engine(tmp_path)
    _seed_source(engine)
    repository = SqlLearningRepository(engine)
    repository.save_course(Course(id="course-1", specialty_id="training", title="Course one"))
    repository.save_version(_version(), as_of=date(2026, 8, 15))
    with engine.begin() as connection:
        connection.execute(
            update(versions)
            .where(versions.c.id == VERSION_ID)
            .values(rescinded_at=datetime(2026, 8, 15, 11, 0, tzinfo=UTC))
        )

    with pytest.raises(LearningPublicationError, match="source_not_effective"):
        repository.publish("course-version-1", reviewed_by="sme", as_of=date(2026, 8, 15))
    engine.dispose()


def test_time_expiry_invalidates_previously_published_version(tmp_path) -> None:
    engine = _engine(tmp_path)
    _seed_source(engine, effective_until=date(2026, 8, 16))
    repository = SqlLearningRepository(engine)
    repository.save_course(Course(id="course-1", specialty_id="training", title="Course one"))
    repository.save_version(_version(), as_of=date(2026, 8, 15))
    repository.publish("course-version-1", reviewed_by="sme", as_of=date(2026, 8, 15))

    refreshed = repository.refresh_publication("course-version-1", as_of=date(2026, 8, 17))
    assert refreshed.state is CoursePublicationState.INVALIDATED
    engine.dispose()
