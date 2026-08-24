from __future__ import annotations

import pytest
from korpus.application.learning_assessment import (
    CheckAttempt,
    CheckOption,
    EvidenceBoundCheck,
    MasteryState,
    grade_check,
    review_queue,
    validate_check_against_lesson,
)
from korpus.domain.learning import (
    LearningObjective,
    Lesson,
    LessonBlock,
    LessonBlockKind,
    SourceBinding,
)


def lesson() -> Lesson:
    binding = SourceBinding(
        id="binding.a",
        document_id="doc",
        version_id="version",
        evidence_span_ids=frozenset({"span"}),
    )
    return Lesson(
        id="lesson.a",
        ordinal=0,
        title="Evidence lesson",
        objectives=(LearningObjective(id="objective.a", statement="Know the rule"),),
        source_bindings=(binding,),
        blocks=(
            LessonBlock(
                id="block.a",
                ordinal=0,
                kind=LessonBlockKind.TEXT,
                title="Block",
                source_binding_ids=frozenset({binding.id}),
            ),
        ),
    )


def check() -> EvidenceBoundCheck:
    return EvidenceBoundCheck(
        id="check.a",
        lesson_id="lesson.a",
        objective_id="objective.a",
        prompt="Which approved statement applies?",
        options=(
            CheckOption(id="a", text="First"),
            CheckOption(id="b", text="Second"),
            CheckOption(id="c", text="Third"),
        ),
        correct_option_ids=frozenset({"b"}),
        source_binding_ids=frozenset({"binding.a"}),
    )


def test_check_is_bound_to_existing_lesson_evidence_and_objective() -> None:
    assert validate_check_against_lesson(check(), lesson()) == ()


def test_check_binding_fails_closed_on_unknown_source_binding() -> None:
    candidate = check().model_copy(update={"source_binding_ids": frozenset({"missing"})})
    assert validate_check_against_lesson(candidate, lesson()) == (
        "unknown_source_binding:check.a:missing",
    )


def test_exact_grading_marks_only_exact_correct_set_as_mastered() -> None:
    passed = grade_check(
        check(), CheckAttempt(check_id="check.a", selected_option_ids=frozenset({"b"}))
    )
    failed = grade_check(
        check(), CheckAttempt(check_id="check.a", selected_option_ids=frozenset({"a"}))
    )
    assert passed.score == 1.0 and passed.mastery is MasteryState.MASTERED
    assert failed.score == 0.0 and failed.mastery is MasteryState.REVIEW_REQUIRED
    assert passed.source_binding_ids == ("binding.a",)


def test_extra_selection_does_not_receive_partial_credit() -> None:
    result = grade_check(
        check(), CheckAttempt(check_id="check.a", selected_option_ids=frozenset({"a", "b"}))
    )
    assert not result.correct
    assert result.score == 0.0


def test_attempt_rejects_undeclared_options() -> None:
    with pytest.raises(ValueError, match="unknown option"):
        grade_check(check(), CheckAttempt(check_id="check.a", selected_option_ids=frozenset({"z"})))


def test_review_queue_is_deterministic_and_deduplicated() -> None:
    failed = grade_check(
        check(), CheckAttempt(check_id="check.a", selected_option_ids=frozenset({"a"}))
    )
    assert review_queue([failed, failed]) == ("objective.a",)
