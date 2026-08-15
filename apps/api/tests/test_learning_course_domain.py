from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from korpus.domain.learning import (
    BoundSourceState,
    Course,
    CourseModule,
    CoursePublication,
    CoursePublicationState,
    CourseVersion,
    LearningObjective,
    Lesson,
    LessonBlock,
    LessonBlockKind,
    Prerequisite,
    SourceBinding,
    validate_course_publication,
)


def _binding(*, span_ids: frozenset[str] = frozenset({"span-1"})) -> SourceBinding:
    return SourceBinding(
        id="source-a",
        document_id="doc-1",
        version_id="version-1",
        evidence_span_ids=span_ids,
    )


def _lesson(
    lesson_id: str,
    ordinal: int,
    *,
    prerequisites: tuple[Prerequisite, ...] = (),
    binding: SourceBinding | None = None,
) -> Lesson:
    source = binding or _binding()
    return Lesson(
        id=lesson_id,
        ordinal=ordinal,
        title=f"Lesson {ordinal}",
        objectives=(
            LearningObjective(id=f"objective-{ordinal}", statement=f"Objective {ordinal}"),
        ),
        source_bindings=(source,),
        blocks=(
            LessonBlock(
                id=f"block-{ordinal}",
                ordinal=0,
                kind=LessonBlockKind.TEXT,
                title="Verified material",
                source_binding_ids=frozenset({source.id}),
            ),
        ),
        prerequisites=prerequisites,
    )


def _version(*lessons: Lesson) -> CourseVersion:
    return CourseVersion(
        id="course-version-1",
        course_id="course-1",
        revision="1.0",
        modules=(
            CourseModule(id="module-1", ordinal=0, title="Module one", lessons=tuple(lessons)),
        ),
    )


def _approved_source(**changes: object) -> BoundSourceState:
    values: dict[str, object] = {
        "document_id": "doc-1",
        "version_id": "version-1",
        "approved": True,
        "evidence_span_ids": frozenset({"span-1", "span-2"}),
        "effective_from": date(2026, 1, 1),
        "effective_until": date(2026, 12, 31),
        "rescinded_at": None,
    }
    values.update(changes)
    return BoundSourceState(**values)


def test_valid_course_graph_is_publishable_only_against_exact_effective_source() -> None:
    first = _lesson("lesson-1", 0)
    second = _lesson("lesson-2", 1, prerequisites=(Prerequisite(lesson_id="lesson-1"),))

    result = validate_course_publication(
        _version(first, second),
        {"version-1": _approved_source()},
        as_of=date(2026, 8, 15),
    )

    assert result.publishable
    assert result.violations == ()


def test_dangling_prerequisite_fails_closed() -> None:
    lesson = _lesson(
        "lesson-1",
        0,
        prerequisites=(Prerequisite(lesson_id="lesson-never-published"),),
    )

    result = validate_course_publication(
        _version(lesson), {"version-1": _approved_source()}, as_of=date(2026, 8, 15)
    )

    assert not result.publishable
    assert result.violations == (
        "dangling_prerequisite:lesson-1:lesson-never-published",
    )


def test_prerequisite_cycle_is_rejected() -> None:
    first = _lesson("lesson-1", 0, prerequisites=(Prerequisite(lesson_id="lesson-2"),))
    second = _lesson("lesson-2", 1, prerequisites=(Prerequisite(lesson_id="lesson-1"),))

    result = validate_course_publication(
        _version(first, second), {"version-1": _approved_source()}, as_of=date(2026, 8, 15)
    )

    assert not result.publishable
    assert any(value.startswith("prerequisite_cycle:") for value in result.violations)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (_approved_source(approved=False), "source_not_effective:lesson-1:version-1"),
        (
            _approved_source(rescinded_at=datetime(2026, 8, 1, tzinfo=UTC)),
            "source_not_effective:lesson-1:version-1",
        ),
        (
            _approved_source(effective_until=date(2026, 8, 14)),
            "source_not_effective:lesson-1:version-1",
        ),
        (
            _approved_source(document_id="other-doc"),
            "source_document_mismatch:lesson-1:source-a",
        ),
    ],
)
def test_unapproved_rescinded_expired_or_mismatched_source_blocks_publication(
    source: BoundSourceState, expected: str
) -> None:
    result = validate_course_publication(
        _version(_lesson("lesson-1", 0)),
        {"version-1": source},
        as_of=date(2026, 8, 15),
    )

    assert not result.publishable
    assert expected in result.violations


def test_evidence_binding_must_reference_exact_existing_spans() -> None:
    lesson = _lesson(
        "lesson-1",
        0,
        binding=_binding(span_ids=frozenset({"span-1", "span-not-in-version"})),
    )

    result = validate_course_publication(
        _version(lesson), {"version-1": _approved_source()}, as_of=date(2026, 8, 15)
    )

    assert result.violations == ("evidence_span_mismatch:lesson-1:source-a",)


def test_missing_source_version_blocks_publication() -> None:
    result = validate_course_publication(
        _version(_lesson("lesson-1", 0)), {}, as_of=date(2026, 8, 15)
    )

    assert result.violations == ("missing_source_version:lesson-1:version-1",)


def test_lesson_block_cannot_reference_unknown_source_binding() -> None:
    with pytest.raises(ValidationError, match="unknown source bindings"):
        Lesson(
            id="lesson-1",
            ordinal=0,
            title="Validated lesson",
            objectives=(LearningObjective(id="objective-1", statement="Validated objective"),),
            source_bindings=(_binding(),),
            blocks=(
                LessonBlock(
                    id="block-1",
                    ordinal=0,
                    kind=LessonBlockKind.TEXT,
                    title="Invalid block",
                    source_binding_ids=frozenset({"missing-binding"}),
                ),
            ),
        )


def test_duplicate_lesson_identity_across_modules_is_rejected() -> None:
    lesson = _lesson("lesson-1", 0)
    with pytest.raises(ValidationError, match="lesson ids must be unique across course version"):
        CourseVersion(
            id="course-version-1",
            course_id="course-1",
            revision="1.0",
            modules=(
                CourseModule(id="module-1", ordinal=0, title="Module one", lessons=(lesson,)),
                CourseModule(id="module-2", ordinal=1, title="Module two", lessons=(lesson,)),
            ),
        )


def test_published_content_models_are_structurally_immutable() -> None:
    course = Course(id="course-1", specialty_id="tactical-medicine", title="Tactical medicine")
    version = _version(_lesson("lesson-1", 0))
    publication = CoursePublication(
        course_version_id=version.id,
        state=CoursePublicationState.PUBLISHED,
        reviewed_at=datetime(2026, 8, 15, tzinfo=UTC),
        reviewed_by="sme-1",
    )

    with pytest.raises(ValidationError, match="frozen"):
        version.revision = "2.0"  # type: ignore[misc]
    assert course.specialty_id == "tactical-medicine"
    assert publication.state is CoursePublicationState.PUBLISHED


def test_published_state_requires_human_review_identity_and_timestamp() -> None:
    with pytest.raises(ValidationError, match="requires review identity and timestamp"):
        CoursePublication(
            course_version_id="course-version-1",
            state=CoursePublicationState.PUBLISHED,
        )
