"""Deterministic, evidence-bound knowledge checks for military learning.

The assessment layer does not generate questions or infer correctness.  An instructor or
approved content pipeline defines a check, binds it to an existing lesson objective and
source bindings, and the runtime performs exact grading.  This keeps training feedback
inside the same evidence boundary as the lesson itself.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from korpus.domain.learning import Lesson


class MasteryState(StrEnum):
    MASTERED = "mastered"
    REVIEW_REQUIRED = "review_required"


class CheckOption(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    text: str = Field(min_length=1, max_length=1000)


class EvidenceBoundCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    lesson_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    objective_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    prompt: str = Field(min_length=3, max_length=2000)
    options: tuple[CheckOption, ...] = Field(min_length=2, max_length=32)
    correct_option_ids: frozenset[str] = Field(min_length=1, max_length=32)
    source_binding_ids: frozenset[str] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_options(self) -> EvidenceBoundCheck:
        option_ids = [item.id for item in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("knowledge-check option ids must be unique")
        unknown = self.correct_option_ids.difference(option_ids)
        if unknown:
            raise ValueError(f"correct options are not declared: {sorted(unknown)}")
        return self


class CheckAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    check_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    selected_option_ids: frozenset[str] = Field(min_length=1, max_length=32)


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    check_id: str
    objective_id: str
    correct: bool
    score: float = Field(ge=0, le=1)
    mastery: MasteryState
    source_binding_ids: tuple[str, ...]


def validate_check_against_lesson(check: EvidenceBoundCheck, lesson: Lesson) -> tuple[str, ...]:
    """Return deterministic publication blockers for an assessment/lesson binding."""
    violations: set[str] = set()
    if check.lesson_id != lesson.id:
        violations.add(f"lesson_mismatch:{check.id}:{check.lesson_id}:{lesson.id}")
    objective_ids = {item.id for item in lesson.objectives}
    if check.objective_id not in objective_ids:
        violations.add(f"unknown_objective:{check.id}:{check.objective_id}")
    binding_ids = {item.id for item in lesson.source_bindings}
    missing = sorted(check.source_binding_ids.difference(binding_ids))
    for binding_id in missing:
        violations.add(f"unknown_source_binding:{check.id}:{binding_id}")
    return tuple(sorted(violations))


def grade_check(check: EvidenceBoundCheck, attempt: CheckAttempt) -> CheckResult:
    """Exact-set grading; extra answers are wrong rather than partially accepted."""
    if attempt.check_id != check.id:
        raise ValueError("attempt check_id does not match knowledge check")
    declared = {option.id for option in check.options}
    unknown = attempt.selected_option_ids.difference(declared)
    if unknown:
        raise ValueError(f"attempt contains unknown option ids: {sorted(unknown)}")
    correct = attempt.selected_option_ids == check.correct_option_ids
    return CheckResult(
        check_id=check.id,
        objective_id=check.objective_id,
        correct=correct,
        score=1.0 if correct else 0.0,
        mastery=MasteryState.MASTERED if correct else MasteryState.REVIEW_REQUIRED,
        source_binding_ids=tuple(sorted(check.source_binding_ids)),
    )


def review_queue(results: list[CheckResult]) -> tuple[str, ...]:
    """Stable objective queue: failed objectives first, deduplicated by objective id."""
    return tuple(sorted({item.objective_id for item in results if not item.correct}))
