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


def test_duplicate_option_ids_are_refused_at_construction() -> None:
    """Grading is an exact set comparison keyed by option id.

    Two options under one id make the selection ambiguous: the attempt names an id, and
    the check cannot say which of the two texts the learner picked.
    """
    with pytest.raises(ValueError, match="option ids must be unique"):
        EvidenceBoundCheck(
            id="check.a",
            lesson_id="lesson.a",
            objective_id="objective.a",
            prompt="Which approved statement applies?",
            options=(CheckOption(id="a", text="First"), CheckOption(id="a", text="Also first")),
            correct_option_ids=frozenset({"a"}),
            source_binding_ids=frozenset({"binding.a"}),
        )


def test_a_correct_option_that_is_not_offered_is_refused() -> None:
    """A key naming an absent option is unanswerable: every attempt scores wrong.

    The failure is silent without this check — the check publishes, learners take it, and
    the mastery signal reads as a cohort that cannot learn the objective.
    """
    with pytest.raises(ValueError, match="correct options are not declared"):
        EvidenceBoundCheck(
            id="check.a",
            lesson_id="lesson.a",
            objective_id="objective.a",
            prompt="Which approved statement applies?",
            options=(CheckOption(id="a", text="First"), CheckOption(id="b", text="Second")),
            correct_option_ids=frozenset({"c"}),
            source_binding_ids=frozenset({"binding.a"}),
        )


def test_a_check_bound_to_another_lesson_is_a_publication_blocker() -> None:
    """The binding is what makes the question answerable from the lesson's own evidence."""
    other = check().model_copy(update={"lesson_id": "lesson.b"})
    violations = validate_check_against_lesson(other, lesson())
    assert any(item.startswith("lesson_mismatch:") for item in violations)


def test_a_check_naming_an_objective_the_lesson_does_not_teach_is_a_blocker() -> None:
    """Mastery is tracked per objective; an unknown one credits nothing."""
    stray = check().model_copy(update={"objective_id": "objective.z"})
    violations = validate_check_against_lesson(stray, lesson())
    assert any(item.startswith("unknown_objective:") for item in violations)


def test_a_check_citing_a_binding_the_lesson_does_not_hold_is_a_blocker() -> None:
    """Every blocker is reported, not just the first: one pass lists all the work."""
    stray = check().model_copy(
        update={"source_binding_ids": frozenset({"binding.a", "binding.z", "binding.y"})}
    )
    violations = validate_check_against_lesson(stray, lesson())
    assert sum(1 for item in violations if item.startswith("unknown_source_binding:")) == 2


def test_a_well_bound_check_has_no_blockers() -> None:
    """The dual: without it a validator that returned every id would look correct."""
    assert validate_check_against_lesson(check(), lesson()) == ()


def test_an_attempt_for_a_different_check_is_refused_rather_than_graded() -> None:
    """Grading it would score one question's answers against another question's key."""
    with pytest.raises(ValueError, match="does not match knowledge check"):
        grade_check(check(), CheckAttempt(check_id="check.b", selected_option_ids=frozenset({"b"})))
