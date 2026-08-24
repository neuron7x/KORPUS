"""Deterministic progression and doctrine-change invalidation for military learning.

No tactical recommendation is produced here.  The module only answers whether a learner
may progress through already-approved training material and which mastered objectives
must be reviewed after their bound source evidence changes.
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from korpus.application.learning_assessment import CheckResult
from korpus.domain.learning import CourseVersion, Lesson


class ObjectiveState(StrEnum):
    UNSEEN = "unseen"
    REVIEW_REQUIRED = "review_required"
    MASTERED = "mastered"


class ObjectiveMastery(BaseModel):
    model_config = ConfigDict(frozen=True)
    objective_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    state: ObjectiveState
    last_check_id: str | None = None
    source_binding_ids: tuple[str, ...] = ()
    updated_at: datetime


class LearnerProgress(BaseModel):
    model_config = ConfigDict(frozen=True)
    subject: str = Field(min_length=1, max_length=200)
    course_version_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    mastery: tuple[ObjectiveMastery, ...] = ()

    def by_objective(self) -> dict[str, ObjectiveMastery]:
        return {item.objective_id: item for item in self.mastery}


def apply_check_result(
    progress: LearnerProgress,
    result: CheckResult,
    *,
    now: datetime | None = None,
) -> LearnerProgress:
    """Replace one objective state using an exact assessment result."""
    observed = (now or datetime.now(UTC)).astimezone(UTC)
    rows = progress.by_objective()
    rows[result.objective_id] = ObjectiveMastery(
        objective_id=result.objective_id,
        state=ObjectiveState.MASTERED if result.correct else ObjectiveState.REVIEW_REQUIRED,
        last_check_id=result.check_id,
        source_binding_ids=tuple(sorted(result.source_binding_ids)),
        updated_at=observed,
    )
    return LearnerProgress(
        subject=progress.subject,
        course_version_id=progress.course_version_id,
        mastery=tuple(rows[key] for key in sorted(rows)),
    )


def lesson_mastered(lesson: Lesson, progress: LearnerProgress) -> bool:
    states = progress.by_objective()
    return all(
        states.get(objective.id) is not None
        and states[objective.id].state is ObjectiveState.MASTERED
        for objective in lesson.objectives
    )


def available_lessons(version: CourseVersion, progress: LearnerProgress) -> tuple[str, ...]:
    """Return lessons whose declared prerequisites are fully mastered.

    This is fail-closed: a missing prerequisite lesson or missing mastery state does not
    unlock anything. Publication validation should already reject dangling prerequisites.
    """
    if progress.course_version_id != version.id:
        raise ValueError("learner progress belongs to another course version")
    lessons = {lesson.id: lesson for module in version.modules for lesson in module.lessons}
    available: list[str] = []
    for module in sorted(version.modules, key=lambda item: item.ordinal):
        for lesson in sorted(module.lessons, key=lambda item: item.ordinal):
            prereq_ids = tuple(item.lesson_id for item in lesson.prerequisites)
            if all(pid in lessons and lesson_mastered(lessons[pid], progress) for pid in prereq_ids):
                available.append(lesson.id)
    return tuple(available)


def invalidate_changed_bindings(
    progress: LearnerProgress,
    *,
    changed_binding_ids: frozenset[str],
    now: datetime | None = None,
) -> LearnerProgress:
    """Invalidate only mastery that depended on changed evidence bindings."""
    if not changed_binding_ids:
        return progress
    observed = (now or datetime.now(UTC)).astimezone(UTC)
    output: list[ObjectiveMastery] = []
    for item in progress.mastery:
        if item.state is ObjectiveState.MASTERED and changed_binding_ids.intersection(item.source_binding_ids):
            output.append(
                ObjectiveMastery(
                    objective_id=item.objective_id,
                    state=ObjectiveState.REVIEW_REQUIRED,
                    last_check_id=item.last_check_id,
                    source_binding_ids=item.source_binding_ids,
                    updated_at=observed,
                )
            )
        else:
            output.append(item)
    return LearnerProgress(
        subject=progress.subject,
        course_version_id=progress.course_version_id,
        mastery=tuple(output),
    )
