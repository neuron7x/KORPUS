"""Immutable learning graph bound to exact canonical KORPUS evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    """Exact source identity; source text never becomes a second truth store."""

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
        binding_ids = [item.id for item in self.source_bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("lesson source binding ids must be unique")
        block_ids = [item.id for item in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("lesson block ids must be unique")
        if len({item.ordinal for item in self.blocks}) != len(self.blocks):
            raise ValueError("lesson block ordinals must be unique")
        objective_ids = [item.id for item in self.objectives]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("lesson objective ids must be unique")
        known = set(binding_ids)
        dangling = {
            binding_id
            for block in self.blocks
            for binding_id in block.source_binding_ids
            if binding_id not in known
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
        ids = [item.id for item in self.lessons]
        if len(ids) != len(set(ids)):
            raise ValueError("module lesson ids must be unique")
        if len({item.ordinal for item in self.lessons}) != len(self.lessons):
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
    def validate_global_identity(self) -> Self:
        module_ids = [item.id for item in self.modules]
        if len(module_ids) != len(set(module_ids)):
            raise ValueError("course module ids must be unique")
        if len({item.ordinal for item in self.modules}) != len(self.modules):
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
    model_config = ConfigDict(frozen=True)
    course_version_id: str = Field(pattern=LEARNING_ID_PATTERN)
    state: CoursePublicationState = CoursePublicationState.DRAFT
    reviewed_at: datetime | None = None
    reviewed_by: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def require_review_for_publication(self) -> Self:
        if self.state is CoursePublicationState.PUBLISHED and (
            self.reviewed_at is None or not self.reviewed_by
        ):
            raise ValueError("published course version requires review identity and timestamp")
        return self


class BoundSourceState(BaseModel):
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
    UNBOUND_BLOCK = "unbound_block"


class PublicationValidation(BaseModel):
    model_config = ConfigDict(frozen=True)
    violations: tuple[str, ...] = ()

    @property
    def publishable(self) -> bool:
        return not self.violations


def _validate_graph_shape(
    lessons: dict[str, Lesson],
) -> tuple[set[str], dict[str, set[str]]]:
    violations: set[str] = set()
    edges: dict[str, set[str]] = {lesson_id: set() for lesson_id in lessons}
    for lesson in lessons.values():
        for block in lesson.blocks:
            if not block.source_binding_ids:
                violations.add(f"{CourseGraphViolation.UNBOUND_BLOCK}:{lesson.id}:{block.id}")
        for prerequisite in lesson.prerequisites:
            if prerequisite.lesson_id == lesson.id:
                violations.add(f"{CourseGraphViolation.SELF_PREREQUISITE}:{lesson.id}")
            elif prerequisite.lesson_id not in lessons:
                violations.add(
                    f"{CourseGraphViolation.DANGLING_PREREQUISITE}:"
                    f"{lesson.id}:{prerequisite.lesson_id}"
                )
            else:
                edges[lesson.id].add(prerequisite.lesson_id)
    return violations, edges


def _validate_source_bindings(
    lessons: dict[str, Lesson],
    source_states: dict[str, BoundSourceState],
    observed: date,
) -> set[str]:
    violations: set[str] = set()
    for lesson in lessons.values():
        for binding in lesson.source_bindings:
            state = source_states.get(binding.version_id)
            if state is None:
                violations.add(
                    f"{CourseGraphViolation.MISSING_SOURCE_VERSION}:"
                    f"{lesson.id}:{binding.version_id}"
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
    return violations


def _validate_acyclic(edges: dict[str, set[str]]) -> set[str]:
    violations: set[str] = set()
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(lesson_id: str) -> None:
        if lesson_id in visiting:
            violations.add(f"{CourseGraphViolation.PREREQUISITE_CYCLE}:{lesson_id}")
            return
        if lesson_id in visited:
            return
        visiting.add(lesson_id)
        for dependency in sorted(edges[lesson_id]):
            visit(dependency)
        visiting.remove(lesson_id)
        visited.add(lesson_id)

    for lesson_id in sorted(edges):
        visit(lesson_id)
    return violations


def validate_course_publication(
    version: CourseVersion,
    source_states: dict[str, BoundSourceState],
    *,
    as_of: date | None = None,
) -> PublicationValidation:
    """Fail closed on graph, source-state, evidence-span, or block-binding defects."""

    observed = as_of or datetime.now(UTC).date()
    lessons = {lesson.id: lesson for module in version.modules for lesson in module.lessons}
    violations, edges = _validate_graph_shape(lessons)
    violations.update(_validate_source_bindings(lessons, source_states, observed))
    violations.update(_validate_acyclic(edges))
    return PublicationValidation(violations=tuple(sorted(violations)))
