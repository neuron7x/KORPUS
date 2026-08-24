"""Role-to-task competency contracts for evidence-bound training.

The graph states what a course is intended to prepare a learner to practise.  It is
not a certification engine: completion and assessment evidence remain separate.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from korpus.domain.learning import LEARNING_ID_PATTERN, CourseVersion


class OperationalRole(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(pattern=LEARNING_ID_PATTERN)
    title: str = Field(min_length=3, max_length=300)
    task_ids: frozenset[str] = Field(min_length=1, max_length=256)


class OperationalTask(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(pattern=LEARNING_ID_PATTERN)
    statement: str = Field(min_length=3, max_length=1000)
    conditions: str = Field(min_length=3, max_length=2000)
    standard: str = Field(min_length=3, max_length=2000)
    competency_ids: frozenset[str] = Field(min_length=1, max_length=256)


class Competency(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(pattern=LEARNING_ID_PATTERN)
    statement: str = Field(min_length=3, max_length=1000)


class CompetencyFramework(BaseModel):
    """An immutable, internally closed role/task/competency graph revision."""

    model_config = ConfigDict(frozen=True)
    id: str = Field(pattern=LEARNING_ID_PATTERN)
    revision: str = Field(min_length=1, max_length=120)
    roles: tuple[OperationalRole, ...] = Field(min_length=1, max_length=512)
    tasks: tuple[OperationalTask, ...] = Field(min_length=1, max_length=4096)
    competencies: tuple[Competency, ...] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_closed_graph(self) -> Self:
        role_ids = [item.id for item in self.roles]
        task_ids = [item.id for item in self.tasks]
        competency_ids = [item.id for item in self.competencies]
        for label, values in (
            ("role", role_ids),
            ("task", task_ids),
            ("competency", competency_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} ids must be unique")

        known_tasks = set(task_ids)
        dangling_tasks = {
            task_id for role in self.roles for task_id in role.task_ids if task_id not in known_tasks
        }
        if dangling_tasks:
            raise ValueError(f"roles reference unknown tasks: {sorted(dangling_tasks)}")

        known_competencies = set(competency_ids)
        dangling_competencies = {
            competency_id
            for task in self.tasks
            for competency_id in task.competency_ids
            if competency_id not in known_competencies
        }
        if dangling_competencies:
            raise ValueError(
                "tasks reference unknown competencies: " f"{sorted(dangling_competencies)}"
            )
        return self


class AlignmentViolation(StrEnum):
    UNKNOWN_ROLE = "unknown_role"
    MISSING_COMPETENCY_OBJECTIVE = "missing_competency_objective"
    UNKNOWN_OBJECTIVE_COMPETENCY = "unknown_objective_competency"


class CourseAlignment(BaseModel):
    model_config = ConfigDict(frozen=True)
    role_id: str
    covered_task_ids: tuple[str, ...] = ()
    uncovered_task_ids: tuple[str, ...] = ()
    violations: tuple[str, ...] = ()

    @property
    def aligned(self) -> bool:
        return not self.violations and not self.uncovered_task_ids


def validate_course_alignment(
    version: CourseVersion,
    framework: CompetencyFramework,
    *,
    role_id: str,
) -> CourseAlignment:
    """Require every competency of every role task to map to a course objective.

    Coverage is deliberately conjunctive.  One covered competency cannot compensate
    for another missing competency, and unknown labels fail closed.
    """

    roles = {role.id: role for role in framework.roles}
    role = roles.get(role_id)
    if role is None:
        return CourseAlignment(
            role_id=role_id,
            violations=(f"{AlignmentViolation.UNKNOWN_ROLE}:{role_id}",),
        )

    known_competencies = {item.id for item in framework.competencies}
    objective_competencies = {
        competency_id
        for module in version.modules
        for lesson in module.lessons
        for objective in lesson.objectives
        for competency_id in objective.competency_ids
    }
    violations = {
        f"{AlignmentViolation.UNKNOWN_OBJECTIVE_COMPETENCY}:{competency_id}"
        for competency_id in objective_competencies - known_competencies
    }
    tasks = {task.id: task for task in framework.tasks}
    covered: list[str] = []
    uncovered: list[str] = []
    for task_id in sorted(role.task_ids):
        missing = tasks[task_id].competency_ids - objective_competencies
        if missing:
            uncovered.append(task_id)
            violations.update(
                f"{AlignmentViolation.MISSING_COMPETENCY_OBJECTIVE}:{task_id}:{competency_id}"
                for competency_id in missing
            )
        else:
            covered.append(task_id)
    return CourseAlignment(
        role_id=role_id,
        covered_task_ids=tuple(covered),
        uncovered_task_ids=tuple(uncovered),
        violations=tuple(sorted(violations)),
    )
