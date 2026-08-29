"""Deterministic reconstruction of immutable learning course-version graphs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Table, select
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.sql.elements import ColumnElement

from korpus.domain.learning import (
    CourseModule,
    CourseVersion,
    LearningObjective,
    Lesson,
    LessonBlock,
    LessonBlockKind,
    Prerequisite,
    SourceBinding,
)
from korpus.infrastructure.learning_schema import (
    learning_block_sources,
    learning_course_versions,
    learning_lesson_blocks,
    learning_lessons,
    learning_modules,
    learning_objective_competencies,
    learning_objectives,
    learning_prerequisites,
    learning_source_binding_spans,
    learning_source_bindings,
)


@dataclass(frozen=True)
class _CourseRows:
    modules: Sequence[RowMapping]
    lessons: Sequence[RowMapping]
    objectives: Sequence[RowMapping]
    objective_competencies: Sequence[RowMapping]
    bindings: Sequence[RowMapping]
    spans: Sequence[RowMapping]
    blocks: Sequence[RowMapping]
    block_sources: Sequence[RowMapping]
    prerequisites: Sequence[RowMapping]


def _version_rows(
    connection: Connection,
    table: Table,
    version_id: str,
    *order_by: ColumnElement[Any],
) -> Sequence[RowMapping]:
    statement = select(table).where(table.c.course_version_id == version_id)
    if order_by:
        statement = statement.order_by(*order_by)
    return connection.execute(statement).mappings().all()


def load_course_version(connection: Connection, version_id: str) -> CourseVersion | None:
    """Load one graph with stable ordering so repeated reads are deterministic."""

    version_row = (
        connection.execute(
            select(learning_course_versions).where(learning_course_versions.c.id == version_id)
        )
        .mappings()
        .first()
    )
    if version_row is None:
        return None

    module_rows = _version_rows(
        connection, learning_modules, version_id, learning_modules.c.ordinal, learning_modules.c.id
    )
    lesson_rows = _version_rows(
        connection,
        learning_lessons,
        version_id,
        learning_lessons.c.module_id,
        learning_lessons.c.ordinal,
        learning_lessons.c.id,
    )
    objective_rows = _version_rows(
        connection,
        learning_objectives,
        version_id,
        learning_objectives.c.lesson_id,
        learning_objectives.c.id,
    )
    objective_competency_rows = _version_rows(
        connection,
        learning_objective_competencies,
        version_id,
        learning_objective_competencies.c.lesson_id,
        learning_objective_competencies.c.objective_id,
        learning_objective_competencies.c.competency_id,
    )
    binding_rows = _version_rows(
        connection,
        learning_source_bindings,
        version_id,
        learning_source_bindings.c.lesson_id,
        learning_source_bindings.c.id,
    )
    span_rows = _version_rows(
        connection,
        learning_source_binding_spans,
        version_id,
        learning_source_binding_spans.c.lesson_id,
        learning_source_binding_spans.c.binding_id,
        learning_source_binding_spans.c.span_id,
    )
    block_rows = _version_rows(
        connection,
        learning_lesson_blocks,
        version_id,
        learning_lesson_blocks.c.lesson_id,
        learning_lesson_blocks.c.ordinal,
        learning_lesson_blocks.c.id,
    )
    block_source_rows = _version_rows(
        connection,
        learning_block_sources,
        version_id,
        learning_block_sources.c.lesson_id,
        learning_block_sources.c.block_id,
        learning_block_sources.c.binding_id,
    )
    prerequisite_rows = _version_rows(
        connection,
        learning_prerequisites,
        version_id,
        learning_prerequisites.c.lesson_id,
        learning_prerequisites.c.prerequisite_lesson_id,
    )
    return _assemble_course_version(
        version_row,
        _CourseRows(
            module_rows,
            lesson_rows,
            objective_rows,
            objective_competency_rows,
            binding_rows,
            span_rows,
            block_rows,
            block_source_rows,
            prerequisite_rows,
        ),
    )


def _assemble_course_version(version_row: RowMapping, rows: _CourseRows) -> CourseVersion:
    objectives: dict[str, list[LearningObjective]] = defaultdict(list)
    objective_competencies: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows.objective_competencies:
        objective_competencies[(str(row["lesson_id"]), str(row["objective_id"]))].add(
            str(row["competency_id"])
        )
    for row in rows.objectives:
        lesson_id = str(row["lesson_id"])
        objective_id = str(row["id"])
        objectives[str(row["lesson_id"])].append(
            LearningObjective(
                id=objective_id,
                statement=str(row["statement"]),
                competency_ids=frozenset(objective_competencies[(lesson_id, objective_id)]),
            )
        )

    binding_spans: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows.spans:
        binding_spans[(str(row["lesson_id"]), str(row["binding_id"]))].add(str(row["span_id"]))

    bindings: dict[str, list[SourceBinding]] = defaultdict(list)
    for row in rows.bindings:
        lesson_id = str(row["lesson_id"])
        binding_id = str(row["id"])
        bindings[lesson_id].append(
            SourceBinding(
                id=binding_id,
                document_id=str(row["document_id"]),
                version_id=str(row["version_id"]),
                evidence_span_ids=frozenset(binding_spans[(lesson_id, binding_id)]),
            )
        )

    block_sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows.block_sources:
        block_sources[(str(row["lesson_id"]), str(row["block_id"]))].add(str(row["binding_id"]))

    blocks: dict[str, list[LessonBlock]] = defaultdict(list)
    for row in rows.blocks:
        lesson_id = str(row["lesson_id"])
        block_id = str(row["id"])
        blocks[lesson_id].append(
            LessonBlock(
                id=block_id,
                ordinal=int(row["ordinal"]),
                kind=LessonBlockKind(str(row["kind"])),
                title=str(row["title"]),
                source_binding_ids=frozenset(block_sources[(lesson_id, block_id)]),
            )
        )

    prerequisites: dict[str, list[Prerequisite]] = defaultdict(list)
    for row in rows.prerequisites:
        prerequisites[str(row["lesson_id"])].append(
            Prerequisite(lesson_id=str(row["prerequisite_lesson_id"]))
        )

    lessons: dict[str, list[Lesson]] = defaultdict(list)
    for row in rows.lessons:
        lesson_id = str(row["id"])
        lessons[str(row["module_id"])].append(
            Lesson(
                id=lesson_id,
                ordinal=int(row["ordinal"]),
                title=str(row["title"]),
                objectives=tuple(objectives[lesson_id]),
                source_bindings=tuple(bindings[lesson_id]),
                blocks=tuple(blocks[lesson_id]),
                prerequisites=tuple(prerequisites[lesson_id]),
            )
        )

    modules = tuple(
        CourseModule(
            id=str(row["id"]),
            ordinal=int(row["ordinal"]),
            title=str(row["title"]),
            lessons=tuple(lessons[str(row["id"])]),
        )
        for row in rows.modules
    )
    return CourseVersion(
        id=str(version_row["id"]),
        course_id=str(version_row["course_id"]),
        revision=str(version_row["revision"]),
        competency_framework_id=version_row["competency_framework_id"],
        competency_framework_revision=version_row["competency_framework_revision"],
        modules=modules,
    )
