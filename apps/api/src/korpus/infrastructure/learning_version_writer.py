"""Low-level insertion of immutable learning course-version graphs."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import insert
from sqlalchemy.engine import Connection

from korpus.domain.learning import CoursePublicationState, CourseVersion
from korpus.infrastructure.learning_schema import (
    learning_block_sources,
    learning_course_versions,
    learning_lesson_blocks,
    learning_lessons,
    learning_modules,
    learning_objectives,
    learning_prerequisites,
    learning_publications,
    learning_source_binding_spans,
    learning_source_bindings,
)


def insert_course_version(
    connection: Connection,
    version: CourseVersion,
    stamp: datetime,
) -> None:
    """Insert one immutable graph in a caller-owned transaction."""

    prerequisite_rows: list[dict[str, str]] = []
    connection.execute(
        insert(learning_course_versions).values(
            id=version.id,
            course_id=version.course_id,
            revision=version.revision,
            created_at=stamp,
        )
    )
    connection.execute(
        insert(learning_publications).values(
            course_version_id=version.id,
            state=CoursePublicationState.DRAFT.value,
            reviewed_at=None,
            reviewed_by=None,
            created_at=stamp,
            updated_at=stamp,
        )
    )
    for module in version.modules:
        connection.execute(
            insert(learning_modules).values(
                course_version_id=version.id,
                id=module.id,
                ordinal=module.ordinal,
                title=module.title,
            )
        )
        for lesson in module.lessons:
            connection.execute(
                insert(learning_lessons).values(
                    course_version_id=version.id,
                    id=lesson.id,
                    module_id=module.id,
                    ordinal=lesson.ordinal,
                    title=lesson.title,
                )
            )
            connection.execute(
                insert(learning_objectives),
                [
                    {
                        "course_version_id": version.id,
                        "lesson_id": lesson.id,
                        "id": objective.id,
                        "statement": objective.statement,
                    }
                    for objective in lesson.objectives
                ],
            )
            for binding in lesson.source_bindings:
                connection.execute(
                    insert(learning_source_bindings).values(
                        course_version_id=version.id,
                        lesson_id=lesson.id,
                        id=binding.id,
                        document_id=binding.document_id,
                        version_id=binding.version_id,
                    )
                )
                connection.execute(
                    insert(learning_source_binding_spans),
                    [
                        {
                            "course_version_id": version.id,
                            "lesson_id": lesson.id,
                            "binding_id": binding.id,
                            "span_id": span_id,
                        }
                        for span_id in sorted(binding.evidence_span_ids)
                    ],
                )
            for block in lesson.blocks:
                connection.execute(
                    insert(learning_lesson_blocks).values(
                        course_version_id=version.id,
                        lesson_id=lesson.id,
                        id=block.id,
                        ordinal=block.ordinal,
                        kind=block.kind.value,
                        title=block.title,
                    )
                )
                if block.source_binding_ids:
                    connection.execute(
                        insert(learning_block_sources),
                        [
                            {
                                "course_version_id": version.id,
                                "lesson_id": lesson.id,
                                "block_id": block.id,
                                "binding_id": binding_id,
                            }
                            for binding_id in sorted(block.source_binding_ids)
                        ],
                    )
            prerequisite_rows.extend(
                {
                    "course_version_id": version.id,
                    "lesson_id": lesson.id,
                    "prerequisite_lesson_id": prerequisite.lesson_id,
                }
                for prerequisite in lesson.prerequisites
            )
    if prerequisite_rows:
        connection.execute(insert(learning_prerequisites), prerequisite_rows)
