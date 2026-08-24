from datetime import UTC, datetime

from korpus.application.learning_assessment import CheckResult, MasteryState
from korpus.application.training_progression import (
    LearnerProgress,
    ObjectiveState,
    apply_check_result,
    available_lessons,
    invalidate_changed_bindings,
)
from korpus.domain.learning import (
    CourseModule,
    CourseVersion,
    LearningObjective,
    Lesson,
    LessonBlock,
    Prerequisite,
    SourceBinding,
)


def _lesson(lid: str, oid: str, ordinal: int, prereq: str | None = None) -> Lesson:
    binding = SourceBinding(id=f"b.{lid}", document_id="doc", version_id="v1", evidence_span_ids=frozenset({"s1"}))
    return Lesson(
        id=lid,
        ordinal=ordinal,
        title=f"Lesson {lid}",
        objectives=(LearningObjective(id=oid, statement="Know the approved source"),),
        source_bindings=(binding,),
        blocks=(LessonBlock(id=f"blk.{lid}", ordinal=0, kind="text", title="Block", source_binding_ids=frozenset({binding.id})),),
        prerequisites=() if prereq is None else (Prerequisite(lesson_id=prereq),),
    )


def _course() -> CourseVersion:
    a = _lesson("l1", "o1", 0)
    b = _lesson("l2", "o2", 1, "l1")
    return CourseVersion(id="cv1", course_id="c1", revision="1", modules=(CourseModule(id="m1", ordinal=0, title="Module", lessons=(a, b)),))


def test_progression_is_prerequisite_aware_and_fail_closed():
    version = _course()
    progress = LearnerProgress(subject="u", course_version_id="cv1")
    assert available_lessons(version, progress) == ("l1",)
    result = CheckResult(check_id="q1", objective_id="o1", correct=True, score=1.0, mastery=MasteryState.MASTERED, source_binding_ids=("b.l1",))
    progress = apply_check_result(progress, result, now=datetime(2026, 8, 20, tzinfo=UTC))
    assert available_lessons(version, progress) == ("l1", "l2")


def test_changed_source_binding_revokes_only_dependent_mastery():
    now = datetime(2026, 8, 20, tzinfo=UTC)
    progress = LearnerProgress(subject="u", course_version_id="cv1")
    for check, objective, binding in (("q1", "o1", "b.l1"), ("q2", "o2", "b.l2")):
        progress = apply_check_result(progress, CheckResult(check_id=check, objective_id=objective, correct=True, score=1.0, mastery=MasteryState.MASTERED, source_binding_ids=(binding,)), now=now)
    changed = invalidate_changed_bindings(progress, changed_binding_ids=frozenset({"b.l1"}), now=now)
    states = changed.by_objective()
    assert states["o1"].state is ObjectiveState.REVIEW_REQUIRED
    assert states["o2"].state is ObjectiveState.MASTERED
