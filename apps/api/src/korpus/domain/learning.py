from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from korpus.domain.models import CORPUS_ID_PATTERN

LEARNING_ID_PATTERN = r"^[a-z0-9][a-z0-9._:-]{0,127}$"


class CoursePublicationState(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    INVALIDATED = "invalidated"
    RETIRED = "retired"


class LessonBlockKind(StrEnum):
    TEXT = "text"
    VIDEO = "video"
    IMAGE = "image"
    SCHEME = "scheme"
    ACTIVITY = "activity"


class LearningObjective(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=LEARNING_ID_PATTERN)
    statement: str = Field(min_length=3, max_length=1000)


class SourceBinding(BaseModel):
    """Exact authoritative source identity used by a lesson.

    The binding deliberately points to an existing KORPUS version and exact evidence
    spans. It carries no copied source text, so learning cannot become a second truth
    store.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=LEARNING_ID_PATTERN)
    document_id: str = Field(min_length=1, max_length=128)
    version_id: str = Field(min_length=1, max_length=128)
    evidence_span_ids: frozenset[str] = Field(min_length=1, max_length=512)


class LessonBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=LEARNING_ID_PATTERN)
    ordinal: int = Field(ge=0, le=100_000)
    kind: LessonBlockKind
    title: str = Field(min_length=1, max_length=500)
    source_binding_ids: frozenset[str] = Field(default_factory=frozenset, max_length=128)


class Prerequisite(BaseModel):
    model_config = ConfigDict(frozen=True)

    lesson_id: str = Field(pattern=LEARNING_ID_PATTERN)


class Lesson(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=LEARNING_ID_PATTERN)
    ordinal: int = Field(ge=0, le=100_000)
    title: str = Field(min_length=3, max_length=500)
    objectives: tuple[LearningObjective, ...] = Field(min_length=1, max_length=128)
    source_bindings: tuple[SourceBinding, ...] = Field(min_length=1, max_length=128)
    blocks: tuple[LessonBlock, ...] = Field(min_length=1, max_length=512)
    prerequisites: tuple[Prerequisite, ...] = Field(default_factory=tuple, max_length=128)

    @model_validator(mode="after")
    def validate_local_references(self) -> Self:
        binding_ids = [binding.id for binding in self.source_bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("lesson source binding ids must be unique")
        block_ids = [block.id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("lesson block ids must be unique")
        if len({block.ordinal for block in self.blocks}) != len(self.blocks):
            raise ValueError("lesson block ordinals must be unique")
        objective_ids = [objective.id for objective in self.objectives]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("lesson objective ids must be unique")
        known_bindings = set(binding_ids)
        dangling = {
            binding_id
            for block in self.blocks
            for binding_id in block.source_binding_ids
            if binding_id not in known_bindings
        }
        if dangling:
            raise ValueError(f"lesson block references unknown source bindings: {sorted(dangling)}")
        return self


class CourseModule(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=LEARNING_ID_PATTERN)
    ordinal: int = Field(ge=0, le=10_000)
    title: str = Field(min_length=3, max_length=500)
    lessons: tuple[Lesson, ...] = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_lesson_order(self) -> Self:
        ids = [lesson.id for lesson in self.lessons]
        if len(ids) != len(set(ids)):
            raise ValueError("module lesson ids must be unique")
        if len({lesson.ordinal for lesson in self.lessons}) != len(self.lessons):
            raise ValueError("module lesson ordinals must be unique")
        return self


class Course(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=LEARNING_ID_PATTERN)
    specialty_id: str = Field(pattern=CORPUS_ID_PATTERN.pattern)
    title: str = Field(min_length=3, max_length=500)


class CourseVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=LEARNING_ID_PATTERN)
    course_id: str = Field(pattern=LEARNING_ID_PATTERN)
    revision: str = Field(min_length=1, max_length=120)
    modules: tuple[CourseModule, ...] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_module_identity(self) -> Self:
        ids = [module.id for module in self.modules]
        if len(ids) != len(set(ids)):
            raise ValueError("course module ids must be unique")
        if len({module.ordinal for module in self.modules}) != len(self.modules):
            raise ValueError("course module ordinals must be unique")
        lesson_ids = [lesson.id for module in self.modules for lesson in module.lessons]
        if len(lesson_ids) != len(set(lesson_ids)):
            raise ValueError("lesson ids must be unique across course version")
        objective_ids = [
            objective.id
            for module in self.modules
            for lesson in module.lessons
            for objective in lesson.objectives
        ]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("objective ids must be unique across course version")
        return self


class CoursePublication(BaseModel):
    """Lifecycle record separated from immutable version content."""

    model_config = ConfigDict(frozen=True)

    course_version_id: str = Field(pattern=LEARNING_ID_PATTERN)
    state: CoursePublicationState = CoursePublicationState.DRAFT
    reviewed_at: datetime | None = None
    reviewed_by: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def require_review_for_publication(self) -> Self:
        if self.state == CoursePublicationState.PUBLISHED and (
            self.reviewed_at is None or not self.reviewed_by
        ):
            raise ValueError("published course version requires review identity and timestamp")
        return self


class BoundSourceState(BaseModel):
    """Canonical source facts projected from KORPUS for publication validation."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    version_id: str
    approved: bool
    evidence_span_ids: frozenset[str]
    effective_from: date | None = None
    effective_until: date | None = None
    rescinded_at: datetime | None = None

    def is_effective(self, as_of: date) -> bool:
        return (
            self.approved
            and self.rescinded_at is None
            and (self.effective_from is None or self.effective_from <= as_of)
            and (self.effective_until is None or self.effective_until >= as_of)
        )


class CourseGraphViolation(StrEnum):
    DANGLING_PREREQUISITE = "dangling_prerequisite"
    SELF_PREREQUISITE = "self_prerequisite"
    PREREQUISITE_CYCLE = "prerequisite_cycle"
    MISSING_SOURCE_VERSION = "missing_source_version"
    SOURCE_DOCUMENT_MISMATCH = "source_document_mismatch"
    SOURCE_NOT_EFFECTIVE = "source_not_effective"
    EVIDENCE_SPAN_MISMATCH = "evidence_span_mismatch"


class PublicationValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    violations: tuple[str, ...] = ()

    @property
    def publishable(self) -> bool:
        return not self.violations


def validate_course_publication(
    version: CourseVersion,
    source_states: dict[str, BoundSourceState],
    *,
    as_of: date | None = None,
) -> PublicationValidation:
    """Fail-closed validation of graph topology and exact source bindings."""

    observed = as_of or datetime.now(UTC).date()
    lessons = {lesson.id: lesson for module in version.modules for lesson in module.lessons}
    violations: set[str] = set()
    edges: dict[str, set[str]] = {lesson_id: set() for lesson_id in lessons}

    for lesson in lessons.values():
        for prerequisite in lesson.prerequisites:
            if prerequisite.lesson_id == lesson.id:
                violations.add(f"{CourseGraphViolation.SELF_PREREQUISITE}:{lesson.id}")
            elif prerequisite.lesson_id not in lessons:
                violations.add(
                    f"{CourseGraphViolation.DANGLING_PREREQUISITE}:{lesson.id}:{prerequisite.lesson_id}"
                )
            else:
                edges[lesson.id].add(prerequisite.lesson_id)
        for binding in lesson.source_bindings:
            state = source_states.get(binding.version_id)
            if state is None:
                violations.add(
                    f"{CourseGraphViolation.MISSING_SOURCE_VERSION}:{lesson.id}:{binding.version_id}"
                )
                continue
            if state.document_id != binding.document_id:
                violations.add(
                    f"{CourseGraphViolation.SOURCE_DOCUMENT_MISMATCH}:{lesson.id}:{binding.id}"
                )
            if not state.is_effective(observed):
                violations.add(
                    f"{CourseGraphViolation.SOURCE_NOT_EFFECTIVE}:{lesson.id}:{binding.version_id}"
                )
            if not binding.evidence_span_ids <= state.evidence_span_ids:
                violations.add(
                    f"{CourseGraphViolation.EVIDENCE_SPAN_MISMATCH}:{lesson.id}:{binding.id}"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(lesson_id: str) -> None:
        if lesson_id in visiting:
            violations.add(f"{CourseGraphViolation.PREREQUISITE_CYCLE}:{lesson_id}")
            return
        if lesson_id in visited:
            return
        visiting.add(lesson_id)
        for dependency in edges[lesson_id]:
            visit(dependency)
        visiting.remove(lesson_id)
        visited.add(lesson_id)

    for lesson_id in sorted(lessons):
        visit(lesson_id)
    return PublicationValidation(violations=tuple(sorted(violations)))
