"""Deterministic reconstruction of immutable learning course-version graphs."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.engine import Connection

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
    learning_objectives,
    learning_prerequisites,
    learning_source_binding_spans,
    learning_source_bindings,
)


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

    module_rows = (
        connection.execute(
            select(learning_modules)
            .where(learning_modules.c.course_version_id == version_id)
            .order_by(learning_modules.c.ordinal, learning_modules.c.id)
        )
        .mappings()
        .all()
    )
    lesson_rows = (
        connection.execute(
            select(learning_lessons)
            .where(learning_lessons.c.course_version_id == version_id)
            .order_by(
                learning_lessons.c.module_id,
                learning_lessons.c.ordinal,
                learning_lessons.c.id,
            )
        )
        .mappings()
        .all()
    )
    objective_rows = (
        connection.execute(
            select(learning_objectives)
            .where(learning_objectives.c.course_version_id == version_id)
            .order_by(learning_objectives.c.lesson_id, learning_objectives.c.id)
        )
        .mappings()
        .all()
    )
    binding_rows = (
        connection.execute(
            select(learning_source_bindings)
            .where(learning_source_bindings.c.course_version_id == version_id)
            .order_by(learning_source_bindings.c.lesson_id, learning_source_bindings.c.id)
        )
        .mappings()
        .all()
    )
    span_rows = (
        connection.execute(
            select(learning_source_binding_spans)
            .where(learning_source_binding_spans.c.course_version_id == version_id)
            .order_by(
                learning_source_binding_spans.c.lesson_id,
                learning_source_binding_spans.c.binding_id,
                learning_source_binding_spans.c.span_id,
            )
        )
        .mappings()
        .all()
    )
    block_rows = (
        connection.execute(
            select(learning_lesson_blocks)
            .where(learning_lesson_blocks.c.course_version_id == version_id)
            .order_by(
                learning_lesson_blocks.c.lesson_id,
                learning_lesson_blocks.c.ordinal,
                learning_lesson_blocks.c.id,
            )
        )
        .mappings()
        .all()
    )
    block_source_rows = (
        connection.execute(
            select(learning_block_sources)
            .where(learning_block_sources.c.course_version_id == version_id)
            .order_by(
                learning_block_sources.c.lesson_id,
                learning_block_sources.c.block_id,
                learning_block_sources.c.binding_id,
            )
        )
        .mappings()
        .all()
    )
    prerequisite_rows = (
        connection.execute(
            select(learning_prerequisites)
            .where(learning_prerequisites.c.course_version_id == version_id)
            .order_by(
                learning_prerequisites.c.lesson_id,
                learning_prerequisites.c.prerequisite_lesson_id,
            )
        )
        .mappings()
        .all()
    )

    objectives: dict[str, list[LearningObjective]] = defaultdict(list)
    for row in objective_rows:
        objectives[str(row["lesson_id"])].append(
            LearningObjective(id=str(row["id"]), statement=str(row["statement"]))
        )

    binding_spans: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in span_rows:
        binding_spans[(str(row["lesson_id"]), str(row["binding_id"]))].add(str(row["span_id"]))

    bindings: dict[str, list[SourceBinding]] = defaultdict(list)
    for row in binding_rows:
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
    for row in block_source_rows:
        block_sources[(str(row["lesson_id"]), str(row["block_id"]))].add(str(row["binding_id"]))

    blocks: dict[str, list[LessonBlock]] = defaultdict(list)
    for row in block_rows:
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
    for row in prerequisite_rows:
        prerequisites[str(row["lesson_id"])].append(
            Prerequisite(lesson_id=str(row["prerequisite_lesson_id"]))
        )

    lessons: dict[str, list[Lesson]] = defaultdict(list)
    for row in lesson_rows:
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
        for row in module_rows
    )
    return CourseVersion(
        id=str(version_row["id"]),
        course_id=str(version_row["course_id"]),
        revision=str(version_row["revision"]),
        modules=modules,
    )
