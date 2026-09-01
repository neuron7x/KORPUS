from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from korpus.domain.learning import (
    BoundSourceState,
    CourseGraphViolation,
    CourseModule,
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
from pydantic import ValidationError


def _lesson(
    lesson_id: str,
    *,
    ordinal: int = 0,
    prerequisite_ids: tuple[str, ...] = (),
    bound: bool = True,
) -> Lesson:
    binding = SourceBinding(
        id=f"binding-{lesson_id}",
        document_id="11111111-1111-1111-1111-111111111111",
        version_id="22222222-2222-2222-2222-222222222222",
        evidence_span_ids=frozenset({"33333333-3333-3333-3333-333333333333"}),
    )
    return Lesson(
        id=lesson_id,
        ordinal=ordinal,
        title=f"Lesson {lesson_id}",
        objectives=(LearningObjective(id=f"objective-{lesson_id}", statement="Know the rule"),),
        source_bindings=(binding,),
        blocks=(
            LessonBlock(
                id=f"block-{lesson_id}",
                ordinal=0,
                kind=LessonBlockKind.TEXT,
                title="Evidence-bound block",
                source_binding_ids=(frozenset({binding.id}) if bound else frozenset()),
            ),
        ),
        prerequisites=tuple(Prerequisite(lesson_id=value) for value in prerequisite_ids),
    )


def _version(*lessons: Lesson) -> CourseVersion:
    return CourseVersion(
        id="course-v1",
        course_id="course",
        revision="1",
        modules=(CourseModule(id="module", ordinal=0, title="Module", lessons=lessons),),
    )


def _source_state(*, approved: bool = True) -> dict[str, BoundSourceState]:
    return {
        "22222222-2222-2222-2222-222222222222": BoundSourceState(
            document_id="11111111-1111-1111-1111-111111111111",
            version_id="22222222-2222-2222-2222-222222222222",
            approved=approved,
            evidence_span_ids=frozenset({"33333333-3333-3333-3333-333333333333"}),
            effective_from=date(2026, 1, 1),
            effective_until=date(2027, 1, 1),
        )
    }


def test_lesson_refuses_dangling_block_binding() -> None:
    with pytest.raises(ValidationError, match="unknown source bindings"):
        Lesson(
            id="lesson",
            ordinal=0,
            title="Lesson title",
            objectives=(LearningObjective(id="objective", statement="Know the rule"),),
            source_bindings=(
                SourceBinding(
                    id="binding",
                    document_id="doc",
                    version_id="version",
                    evidence_span_ids=frozenset({"span"}),
                ),
            ),
            blocks=(
                LessonBlock(
                    id="block",
                    ordinal=0,
                    kind=LessonBlockKind.TEXT,
                    title="Block",
                    source_binding_ids=frozenset({"missing"}),
                ),
            ),
        )


def test_course_version_refuses_duplicate_lesson_identity_across_modules() -> None:
    lesson = _lesson("lesson")
    with pytest.raises(ValidationError, match="lesson ids must be unique"):
        CourseVersion(
            id="course-v1",
            course_id="course",
            revision="1",
            modules=(
                CourseModule(id="m1", ordinal=0, title="First", lessons=(lesson,)),
                CourseModule(id="m2", ordinal=1, title="Second", lessons=(lesson,)),
            ),
        )


def test_publication_validation_passes_exact_effective_source_binding() -> None:
    result = validate_course_publication(
        _version(_lesson("lesson")), _source_state(), as_of=date(2026, 8, 16)
    )
    assert result.publishable
    assert result.violations == ()


def test_publication_validation_fails_closed_on_missing_source() -> None:
    result = validate_course_publication(_version(_lesson("lesson")), {}, as_of=date(2026, 8, 16))
    assert not result.publishable
    assert result.violations == (
        f"{CourseGraphViolation.MISSING_SOURCE_VERSION}:lesson:"
        "22222222-2222-2222-2222-222222222222",
    )


def test_publication_validation_rejects_unapproved_source() -> None:
    result = validate_course_publication(
        _version(_lesson("lesson")), _source_state(approved=False), as_of=date(2026, 8, 16)
    )
    assert any(
        item.startswith(f"{CourseGraphViolation.SOURCE_NOT_EFFECTIVE}:lesson:")
        for item in result.violations
    )


def test_publication_validation_rejects_unbound_block() -> None:
    result = validate_course_publication(
        _version(_lesson("lesson", bound=False)), _source_state(), as_of=date(2026, 8, 16)
    )
    assert result.violations == (f"{CourseGraphViolation.UNBOUND_BLOCK}:lesson:block-lesson",)


def test_publication_validation_rejects_dangling_prerequisite() -> None:
    result = validate_course_publication(
        _version(_lesson("lesson", prerequisite_ids=("missing",))),
        _source_state(),
        as_of=date(2026, 8, 16),
    )
    assert f"{CourseGraphViolation.DANGLING_PREREQUISITE}:lesson:missing" in result.violations


def test_publication_validation_detects_prerequisite_cycle_deterministically() -> None:
    version = _version(
        _lesson("a", ordinal=0, prerequisite_ids=("b",)),
        _lesson("b", ordinal=1, prerequisite_ids=("a",)),
    )
    result = validate_course_publication(version, _source_state(), as_of=date(2026, 8, 16))
    assert not result.publishable
    assert result.violations == tuple(sorted(result.violations))
    assert any(
        item.startswith(f"{CourseGraphViolation.PREREQUISITE_CYCLE}:") for item in result.violations
    )


def test_source_effectiveness_respects_rescission_and_window() -> None:
    state = BoundSourceState(
        document_id="doc",
        version_id="version",
        approved=True,
        evidence_span_ids=frozenset({"span"}),
        effective_from=date(2026, 1, 1),
        effective_until=date(2026, 12, 31),
        rescinded_at=datetime(2026, 8, 16, tzinfo=UTC),
    )
    assert not state.is_effective(date(2026, 8, 16))


def test_lesson_refuses_duplicate_source_binding_identity() -> None:
    binding = SourceBinding(
        id="binding",
        document_id="doc",
        version_id="version",
        evidence_span_ids=frozenset({"span"}),
    )
    with pytest.raises(ValidationError, match="source binding ids must be unique"):
        Lesson(
            id="lesson",
            ordinal=0,
            title="Lesson title",
            objectives=(LearningObjective(id="objective", statement="Know the rule"),),
            source_bindings=(binding, binding),
            blocks=(
                LessonBlock(
                    id="block",
                    ordinal=0,
                    kind=LessonBlockKind.TEXT,
                    title="Block",
                    source_binding_ids=frozenset({"binding"}),
                ),
            ),
        )


def test_lesson_refuses_duplicate_block_identity() -> None:
    binding = SourceBinding(
        id="binding",
        document_id="doc",
        version_id="version",
        evidence_span_ids=frozenset({"span"}),
    )
    block = LessonBlock(
        id="block",
        ordinal=0,
        kind=LessonBlockKind.TEXT,
        title="Block",
        source_binding_ids=frozenset({"binding"}),
    )
    with pytest.raises(ValidationError, match="block ids must be unique"):
        Lesson(
            id="lesson",
            ordinal=0,
            title="Lesson title",
            objectives=(LearningObjective(id="objective", statement="Know the rule"),),
            source_bindings=(binding,),
            blocks=(block, block.model_copy(update={"ordinal": 1})),
        )


def test_lesson_refuses_duplicate_block_ordinal() -> None:
    binding = SourceBinding(
        id="binding",
        document_id="doc",
        version_id="version",
        evidence_span_ids=frozenset({"span"}),
    )
    with pytest.raises(ValidationError, match="block ordinals must be unique"):
        Lesson(
            id="lesson",
            ordinal=0,
            title="Lesson title",
            objectives=(LearningObjective(id="objective", statement="Know the rule"),),
            source_bindings=(binding,),
            blocks=(
                LessonBlock(
                    id="block-a",
                    ordinal=0,
                    kind=LessonBlockKind.TEXT,
                    title="Block A",
                    source_binding_ids=frozenset({"binding"}),
                ),
                LessonBlock(
                    id="block-b",
                    ordinal=0,
                    kind=LessonBlockKind.TEXT,
                    title="Block B",
                    source_binding_ids=frozenset({"binding"}),
                ),
            ),
        )


def test_lesson_refuses_duplicate_objective_identity() -> None:
    binding = SourceBinding(
        id="binding",
        document_id="doc",
        version_id="version",
        evidence_span_ids=frozenset({"span"}),
    )
    objective = LearningObjective(id="objective", statement="Know the rule")
    with pytest.raises(ValidationError, match="objective ids must be unique"):
        Lesson(
            id="lesson",
            ordinal=0,
            title="Lesson title",
            objectives=(objective, objective),
            source_bindings=(binding,),
            blocks=(
                LessonBlock(
                    id="block",
                    ordinal=0,
                    kind=LessonBlockKind.TEXT,
                    title="Block",
                    source_binding_ids=frozenset({"binding"}),
                ),
            ),
        )


def test_module_refuses_duplicate_lesson_identity() -> None:
    lesson = _lesson("lesson")
    with pytest.raises(ValidationError, match="module lesson ids must be unique"):
        CourseModule(
            id="module",
            ordinal=0,
            title="Module",
            lessons=(lesson, lesson.model_copy(update={"ordinal": 1})),
        )


def test_module_refuses_duplicate_lesson_ordinal() -> None:
    with pytest.raises(ValidationError, match="lesson ordinals must be unique"):
        CourseModule(
            id="module",
            ordinal=0,
            title="Module",
            lessons=(_lesson("a", ordinal=0), _lesson("b", ordinal=0)),
        )


def test_course_version_refuses_duplicate_module_identity() -> None:
    first = CourseModule(id="module", ordinal=0, title="First", lessons=(_lesson("a"),))
    second = CourseModule(id="module", ordinal=1, title="Second", lessons=(_lesson("b"),))
    with pytest.raises(ValidationError, match="course module ids must be unique"):
        CourseVersion(
            id="course-v1",
            course_id="course",
            revision="1",
            modules=(first, second),
        )


def test_course_version_refuses_duplicate_module_ordinal() -> None:
    with pytest.raises(ValidationError, match="course module ordinals must be unique"):
        CourseVersion(
            id="course-v1",
            course_id="course",
            revision="1",
            modules=(
                CourseModule(id="m1", ordinal=0, title="First", lessons=(_lesson("a"),)),
                CourseModule(id="m2", ordinal=0, title="Second", lessons=(_lesson("b"),)),
            ),
        )


def test_course_version_refuses_duplicate_objective_identity_across_lessons() -> None:
    first = _lesson("a", ordinal=0)
    second = _lesson("b", ordinal=1).model_copy(update={"objectives": first.objectives})
    with pytest.raises(ValidationError, match="objective ids must be unique across course version"):
        _version(first, second)


def test_course_publication_refuses_missing_review_identity() -> None:
    from korpus.domain.learning import CoursePublication

    with pytest.raises(ValidationError, match="requires review identity"):
        CoursePublication(
            course_version_id="course-v1",
            state=CoursePublicationState.PUBLISHED,
            reviewed_at=datetime(2026, 8, 16, tzinfo=UTC),
            reviewed_by="",
        )


def test_publication_validation_rejects_self_prerequisite() -> None:
    result = validate_course_publication(
        _version(_lesson("lesson", prerequisite_ids=("lesson",))),
        _source_state(),
        as_of=date(2026, 8, 16),
    )
    assert f"{CourseGraphViolation.SELF_PREREQUISITE}:lesson" in result.violations


def test_publication_validation_rejects_source_document_mismatch() -> None:
    states = _source_state()
    state = states["22222222-2222-2222-2222-222222222222"]
    states[state.version_id] = state.model_copy(update={"document_id": "different-document"})
    result = validate_course_publication(
        _version(_lesson("lesson")), states, as_of=date(2026, 8, 16)
    )
    assert (
        f"{CourseGraphViolation.SOURCE_DOCUMENT_MISMATCH}:lesson:binding-lesson"
        in result.violations
    )


def test_publication_validation_rejects_evidence_span_mismatch() -> None:
    states = _source_state()
    state = states["22222222-2222-2222-2222-222222222222"]
    states[state.version_id] = state.model_copy(update={"evidence_span_ids": frozenset({"other"})})
    result = validate_course_publication(
        _version(_lesson("lesson")), states, as_of=date(2026, 8, 16)
    )
    assert (
        f"{CourseGraphViolation.EVIDENCE_SPAN_MISMATCH}:lesson:binding-lesson" in result.violations
    )


def test_a_binding_that_cites_one_held_span_and_one_absent_span_is_rejected() -> None:
    """Часткове перекриття — це і є справжній випадок, і його не перевіряв ніхто.

    Сусідній тест підміняє прольоти джерела ЦІЛКОМ (`{"other"}`), тож «включення» і
    «будь-який перетин» дають на ньому однакову відповідь. Мутант
    M495_ANY_OVERLAP_OF_EVIDENCE_SPANS_IS_ENOUGH_TO_PUBLISH пережив його 01.09.2026:
    перевірка була зелена, бо міряла вужче за те, що охороняє.

    Стан, заради якого правило існує, інший і буденний: версію джерела переглянуто,
    один проліт зник, урок далі цитує обидва. Під слабшим правилом такий курс
    публікується, і читач бачить посилання на проліт, якого у схваленому джерелі
    немає — тобто рівно та поломка, яку `EVIDENCE_SPAN_MISMATCH` мусить ловити.
    """
    held = "33333333-3333-3333-3333-333333333333"
    removed = "44444444-4444-4444-4444-444444444444"
    lesson = Lesson(
        id="lesson",
        ordinal=0,
        title="Lesson lesson",
        objectives=(LearningObjective(id="objective-lesson", statement="Know the rule"),),
        source_bindings=(
            SourceBinding(
                id="binding-lesson",
                document_id="11111111-1111-1111-1111-111111111111",
                version_id="22222222-2222-2222-2222-222222222222",
                evidence_span_ids=frozenset({held, removed}),
            ),
        ),
        blocks=(
            LessonBlock(
                id="block-lesson",
                ordinal=0,
                kind=LessonBlockKind.TEXT,
                title="Evidence-bound block",
                source_binding_ids=frozenset({"binding-lesson"}),
            ),
        ),
    )

    result = validate_course_publication(_version(lesson), _source_state(), as_of=date(2026, 8, 16))

    assert (
        f"{CourseGraphViolation.EVIDENCE_SPAN_MISMATCH}:lesson:binding-lesson" in result.violations
    )
    assert not result.publishable
