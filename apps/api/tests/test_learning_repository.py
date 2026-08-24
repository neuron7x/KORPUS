from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import insert, update

from korpus.domain.learning import (
    Course,
    CourseModule,
    CoursePublicationState,
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
from korpus.infrastructure.learning_repository import LearningStateError, SqlLearningRepository
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.schema import documents, spans, versions

DOC_ID = UUID("11111111-1111-1111-1111-111111111111")
VERSION_ID = UUID("22222222-2222-2222-2222-222222222222")
SPAN_ID = UUID("33333333-3333-3333-3333-333333333333")


def _source(repository: SqlRepository) -> None:
    document = DocumentRecord(
        id=DOC_ID,
        canonical_title="Canonical source",
        corpus_id="public",
        issuer="Authority",
        jurisdiction="UA",
        document_type="standard",
        access_tier=AccessTier.PUBLIC,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        id=VERSION_ID,
        document_id=DOC_ID,
        revision="1",
        source_hash="a" * 64,
        object_key="objects/source",
        mime_type="text/plain",
        publication_date=date(2026, 1, 1),
        effective_from=date(2026, 1, 1),
        effective_until=date(2027, 1, 1),
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.APPROVED,
        approved_at=datetime(2026, 1, 2, tzinfo=UTC),
        approved_by="reviewer",
        is_current=True,
    )
    span = EvidenceSpanRecord(
        id=SPAN_ID,
        version_id=VERSION_ID,
        ordinal=0,
        text="Exact authoritative evidence.",
    )
    with repository.engine.begin() as connection:
        connection.execute(insert(documents).values(**row_mapping.document_values(document)))
        connection.execute(insert(versions).values(**row_mapping.version_values(version)))
        connection.execute(insert(spans).values(**row_mapping.span_values(span)))


def _version(*, bound: bool = True) -> CourseVersion:
    binding = SourceBinding(
        id="binding",
        document_id=str(DOC_ID),
        version_id=str(VERSION_ID),
        evidence_span_ids=frozenset({str(SPAN_ID)}),
    )
    lesson = Lesson(
        id="lesson",
        ordinal=0,
        title="Evidence lesson",
        objectives=(LearningObjective(id="objective", statement="Know the evidence"),),
        source_bindings=(binding,),
        blocks=(
            LessonBlock(
                id="block",
                ordinal=0,
                kind=LessonBlockKind.TEXT,
                title="Exact evidence block",
                source_binding_ids=(frozenset({binding.id}) if bound else frozenset()),
            ),
        ),
    )
    return CourseVersion(
        id="course-v1",
        course_id="course",
        revision="1",
        modules=(CourseModule(id="module", ordinal=0, title="Module", lessons=(lesson,)),),
    )


@pytest.fixture
def stores(tmp_path: Path) -> tuple[SqlRepository, SqlLearningRepository]:
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'learning.db'}",
        "audit-key",
        audit_anchor_path=tmp_path / "anchor.json",
    )
    repository.initialize()
    _source(repository)
    learning = SqlLearningRepository(repository.engine)
    learning.create_course(Course(id="course", specialty_id="public", title="Course"))
    return repository, learning


def test_learning_repository_round_trip_and_publish(stores) -> None:
    _, learning = stores
    version = _version()
    learning.create_version(version)
    assert learning.get_version(version.id) == version
    assert learning.validate_version(version.id, as_of=date(2026, 8, 16)).publishable
    publication = learning.publish_version(
        version.id,
        reviewed_by="course-reviewer",
        reviewed_at=datetime(2026, 8, 16, 12, tzinfo=UTC),
        as_of=date(2026, 8, 16),
    )
    assert publication.state is CoursePublicationState.PUBLISHED
    assert learning.get_publication(version.id) == publication


def test_learning_repository_refuses_source_less_block(stores) -> None:
    _, learning = stores
    version = _version(bound=False)
    learning.create_version(version)
    with pytest.raises(LearningStateError, match="unbound_block"):
        learning.publish_version(version.id, reviewed_by="course-reviewer", as_of=date(2026, 8, 16))


def test_learning_repository_refuses_rescinded_source(stores) -> None:
    repository, learning = stores
    version = _version()
    learning.create_version(version)
    with repository.engine.begin() as connection:
        connection.execute(
            update(versions)
            .where(versions.c.id == str(VERSION_ID))
            .values(rescinded_at=datetime(2026, 8, 15, tzinfo=UTC))
        )
    with pytest.raises(LearningStateError, match="source_not_effective"):
        learning.publish_version(version.id, reviewed_by="course-reviewer", as_of=date(2026, 8, 16))


def test_published_learning_history_cannot_be_deleted(stores) -> None:
    _, learning = stores
    version = _version()
    learning.create_version(version)
    learning.publish_version(version.id, reviewed_by="course-reviewer", as_of=date(2026, 8, 16))
    with pytest.raises(LearningStateError, match="cannot be deleted"):
        learning.delete_draft_version(version.id)


def test_draft_learning_version_can_be_deleted(stores) -> None:
    _, learning = stores
    version = _version()
    learning.create_version(version)
    assert learning.delete_draft_version(version.id)
    assert learning.get_version(version.id) is None


def test_serving_lane_revalidates_published_source_state(stores) -> None:
    _, learning = stores
    version = _version()
    learning.create_version(version)
    learning.publish_version(version.id, reviewed_by="course-reviewer", as_of=date(2026, 8, 16))
    assert learning.get_serving_version(version.id, as_of=date(2026, 8, 16)) == version


def test_serving_lane_invalidates_content_after_source_expiry(stores) -> None:
    _, learning = stores
    version = _version()
    learning.create_version(version)
    learning.publish_version(version.id, reviewed_by="course-reviewer", as_of=date(2026, 8, 16))
    with pytest.raises(LearningStateError, match="no longer source-valid"):
        learning.get_serving_version(version.id, as_of=date(2027, 1, 2))
    publication = learning.get_publication(version.id)
    assert publication is not None
    assert publication.state is CoursePublicationState.INVALIDATED


def test_learning_repository_course_lookup_is_explicit(stores) -> None:
    _, learning = stores
    assert learning.get_course("course") == Course(id="course", specialty_id="public", title="Course")
    assert learning.get_course("missing") is None


def test_learning_repository_refuses_version_for_unknown_course(stores) -> None:
    _, learning = stores
    with pytest.raises(LookupError, match="course not found"):
        learning.create_version(_version().model_copy(update={"course_id": "missing"}))


def test_learning_repository_normalizes_duplicate_version_constraint(stores) -> None:
    _, learning = stores
    version = _version()
    learning.create_version(version)
    with pytest.raises(LearningStateError, match="persistence constraints"):
        learning.create_version(version)


def test_learning_repository_missing_publication_is_none(stores) -> None:
    _, learning = stores
    assert learning.get_publication("missing") is None


def test_learning_repository_validate_missing_version_fails_closed(stores) -> None:
    _, learning = stores
    with pytest.raises(LookupError, match="course version not found"):
        learning.validate_version("missing", as_of=date(2026, 8, 16))


def test_learning_repository_serving_refuses_missing_and_draft(stores) -> None:
    _, learning = stores
    with pytest.raises(LookupError, match="course version not found"):
        learning.get_serving_version("missing", as_of=date(2026, 8, 16))
    version = _version()
    learning.create_version(version)
    with pytest.raises(LearningStateError, match="not serving from state draft"):
        learning.get_serving_version(version.id, as_of=date(2026, 8, 16))


def test_learning_repository_publish_requires_nonblank_reviewer(stores) -> None:
    _, learning = stores
    learning.create_version(_version())
    with pytest.raises(ValueError, match="reviewed_by must be non-empty"):
        learning.publish_version("course-v1", reviewed_by="   ", as_of=date(2026, 8, 16))


def test_learning_repository_publish_refuses_missing_and_nondraft(stores) -> None:
    _, learning = stores
    with pytest.raises(LookupError, match="course version not found"):
        learning.publish_version("missing", reviewed_by="reviewer", as_of=date(2026, 8, 16))
    version = _version()
    learning.create_version(version)
    learning.publish_version(version.id, reviewed_by="reviewer", as_of=date(2026, 8, 16))
    with pytest.raises(LearningStateError, match="not publishable from state published"):
        learning.publish_version(version.id, reviewed_by="reviewer", as_of=date(2026, 8, 16))


def test_learning_repository_detects_publication_version_inconsistency(stores, monkeypatch) -> None:
    import korpus.infrastructure.learning_repository as learning_repository_module

    _, learning = stores
    version = _version()
    learning.create_version(version)
    learning.publish_version(version.id, reviewed_by="reviewer", as_of=date(2026, 8, 16))
    monkeypatch.setattr(learning_repository_module, "load_course_version", lambda *_: None)
    with pytest.raises(LookupError, match="course version not found"):
        learning.get_serving_version(version.id, as_of=date(2026, 8, 16))


def test_learning_repository_detects_draft_version_inconsistency_on_publish(stores, monkeypatch) -> None:
    import korpus.infrastructure.learning_repository as learning_repository_module

    _, learning = stores
    version = _version()
    learning.create_version(version)
    monkeypatch.setattr(learning_repository_module, "load_course_version", lambda *_: None)
    with pytest.raises(LookupError, match="course version not found"):
        learning.publish_version(version.id, reviewed_by="reviewer", as_of=date(2026, 8, 16))


def test_learning_repository_retirement_state_machine(stores) -> None:
    _, learning = stores
    with pytest.raises(LookupError, match="course version not found"):
        learning.retire_version("missing")
    version = _version()
    learning.create_version(version)
    with pytest.raises(LearningStateError, match="cannot retire learning state draft"):
        learning.retire_version(version.id)
    reviewed_at = datetime(2026, 8, 16, 12, 0)
    learning.publish_version(
        version.id,
        reviewed_by="reviewer",
        reviewed_at=reviewed_at,
        as_of=date(2026, 8, 16),
    )
    retired = learning.retire_version(version.id, retired_at=datetime(2026, 8, 16, 13, tzinfo=UTC))
    assert retired.state is CoursePublicationState.RETIRED
    assert retired.reviewed_at is not None
    assert retired.reviewed_at.tzinfo is UTC
    assert retired.reviewed_by == "reviewer"


def test_learning_repository_delete_missing_draft_is_false(stores) -> None:
    _, learning = stores
    assert not learning.delete_draft_version("missing")


def test_learning_repository_round_trips_prerequisite_edges(stores) -> None:
    _, learning = stores
    binding_a = SourceBinding(
        id="binding-a",
        document_id=str(DOC_ID),
        version_id=str(VERSION_ID),
        evidence_span_ids=frozenset({str(SPAN_ID)}),
    )
    binding_b = binding_a.model_copy(update={"id": "binding-b"})
    first = Lesson(
        id="first",
        ordinal=0,
        title="First lesson",
        objectives=(LearningObjective(id="objective-first", statement="Know first evidence"),),
        source_bindings=(binding_a,),
        blocks=(
            LessonBlock(
                id="block-first",
                ordinal=0,
                kind=LessonBlockKind.TEXT,
                title="First block",
                source_binding_ids=frozenset({binding_a.id}),
            ),
        ),
    )
    second = Lesson(
        id="second",
        ordinal=1,
        title="Second lesson",
        objectives=(LearningObjective(id="objective-second", statement="Know second evidence"),),
        source_bindings=(binding_b,),
        blocks=(
            LessonBlock(
                id="block-second",
                ordinal=0,
                kind=LessonBlockKind.TEXT,
                title="Second block",
                source_binding_ids=frozenset({binding_b.id}),
            ),
        ),
        prerequisites=(Prerequisite(lesson_id="first"),),
    )
    version = CourseVersion(
        id="course-prereq-v1",
        course_id="course",
        revision="prereq-1",
        modules=(CourseModule(id="module-prereq", ordinal=0, title="Module prereq", lessons=(first, second)),),
    )
    learning.create_version(version)
    assert learning.get_version(version.id) == version


def test_empty_learning_source_projection_short_circuits(stores) -> None:
    from types import SimpleNamespace

    from korpus.infrastructure.learning_source_state import load_bound_source_states

    repository, _ = stores
    with repository.engine.connect() as connection:
        assert load_bound_source_states(connection, SimpleNamespace(modules=())) == {}
