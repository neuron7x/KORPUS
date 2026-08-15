from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection, Engine

from korpus.domain.learning import (
    BoundSourceState,
    Course,
    CourseModule,
    CoursePublication,
    CoursePublicationState,
    CourseVersion,
    LearningObjective,
    Lesson,
    LessonBlock,
    LessonBlockKind,
    Prerequisite,
    SourceBinding,
    validate_course_publication,
)
from korpus.infrastructure.learning_schema import (
    learning_block_sources,
    learning_course_versions,
    learning_courses,
    learning_lesson_blocks,
    learning_lessons,
    learning_modules,
    learning_objectives,
    learning_prerequisites,
    learning_publications,
    learning_source_binding_spans,
    learning_source_bindings,
)
from korpus.infrastructure.schema import spans, versions


class LearningPublicationError(RuntimeError):
    pass


class SqlLearningRepository:
    """Persistence boundary for immutable course versions over canonical KORPUS evidence."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save_course(self, course: Course) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(learning_courses).values(
                    id=course.id,
                    specialty_id=course.specialty_id,
                    title=course.title,
                    created_at=datetime.now(UTC),
                )
            )

    def save_version(self, version: CourseVersion, *, as_of: date | None = None) -> None:
        with self.engine.begin() as connection:
            source_states = self._source_states_for_version(connection, version)
            validation = validate_course_publication(version, source_states, as_of=as_of)
            if not validation.publishable:
                raise LearningPublicationError(
                    "course version cannot be persisted: " + "; ".join(validation.violations)
                )
            stamp = datetime.now(UTC)
            connection.execute(
                insert(learning_course_versions).values(
                    id=version.id,
                    course_id=version.course_id,
                    revision=version.revision,
                    created_at=stamp,
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
                    self._insert_lesson(connection, version.id, module.id, lesson)
            connection.execute(
                insert(learning_publications).values(
                    course_version_id=version.id,
                    state=CoursePublicationState.DRAFT.value,
                    reviewed_at=None,
                    reviewed_by=None,
                    updated_at=stamp,
                )
            )

    def load_version(self, version_id: str) -> CourseVersion | None:
        with self.engine.begin() as connection:
            return self._load_version(connection, version_id)

    def publish(
        self,
        version_id: str,
        *,
        reviewed_by: str,
        reviewed_at: datetime | None = None,
        as_of: date | None = None,
    ) -> CoursePublication:
        reviewer = reviewed_by.strip()
        if not reviewer:
            raise ValueError("reviewed_by is required")
        with self.engine.begin() as connection:
            version = self._load_version(connection, version_id)
            if version is None:
                raise LookupError("course version not found")
            source_states = self._source_states_for_version(connection, version)
            validation = validate_course_publication(version, source_states, as_of=as_of)
            if not validation.publishable:
                raise LearningPublicationError(
                    "course version is not publishable: " + "; ".join(validation.violations)
                )
            stamp = reviewed_at or datetime.now(UTC)
            current = connection.execute(
                select(learning_publications).where(
                    learning_publications.c.course_version_id == version_id
                )
            ).mappings().one()
            if current["state"] == CoursePublicationState.RETIRED.value:
                raise LearningPublicationError("retired course version cannot be republished")
            connection.execute(
                update(learning_publications)
                .where(learning_publications.c.course_version_id == version_id)
                .values(
                    state=CoursePublicationState.PUBLISHED.value,
                    reviewed_at=stamp,
                    reviewed_by=reviewer,
                    updated_at=stamp,
                )
            )
            return CoursePublication(
                course_version_id=version_id,
                state=CoursePublicationState.PUBLISHED,
                reviewed_at=stamp,
                reviewed_by=reviewer,
            )

    def refresh_publication(
        self,
        version_id: str,
        *,
        as_of: date | None = None,
    ) -> CoursePublication:
        """Revalidate a published version so time-based source expiry fails closed."""
        with self.engine.begin() as connection:
            row = connection.execute(
                select(learning_publications).where(
                    learning_publications.c.course_version_id == version_id
                )
            ).mappings().first()
            if row is None:
                raise LookupError("course publication not found")
            state = CoursePublicationState(row["state"])
            if state is CoursePublicationState.PUBLISHED:
                version = self._load_version(connection, version_id)
                if version is None:
                    raise LookupError("course version not found")
                validation = validate_course_publication(
                    version,
                    self._source_states_for_version(connection, version),
                    as_of=as_of,
                )
                if not validation.publishable:
                    state = CoursePublicationState.INVALIDATED
                    connection.execute(
                        update(learning_publications)
                        .where(learning_publications.c.course_version_id == version_id)
                        .values(state=state.value, updated_at=datetime.now(UTC))
                    )
            return CoursePublication(
                course_version_id=version_id,
                state=state,
                reviewed_at=row["reviewed_at"],
                reviewed_by=row["reviewed_by"],
            )

    @staticmethod
    def _insert_lesson(
        connection: Connection,
        course_version_id: str,
        module_id: str,
        lesson: Lesson,
    ) -> None:
        connection.execute(
            insert(learning_lessons).values(
                course_version_id=course_version_id,
                id=lesson.id,
                module_id=module_id,
                ordinal=lesson.ordinal,
                title=lesson.title,
            )
        )
        for ordinal, objective in enumerate(lesson.objectives):
            connection.execute(
                insert(learning_objectives).values(
                    course_version_id=course_version_id,
                    lesson_id=lesson.id,
                    id=objective.id,
                    ordinal=ordinal,
                    statement=objective.statement,
                )
            )
        for binding in lesson.source_bindings:
            connection.execute(
                insert(learning_source_bindings).values(
                    course_version_id=course_version_id,
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
                        "course_version_id": course_version_id,
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
                    course_version_id=course_version_id,
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
                            "course_version_id": course_version_id,
                            "lesson_id": lesson.id,
                            "block_id": block.id,
                            "binding_id": binding_id,
                        }
                        for binding_id in sorted(block.source_binding_ids)
                    ],
                )
        if lesson.prerequisites:
            connection.execute(
                insert(learning_prerequisites),
                [
                    {
                        "course_version_id": course_version_id,
                        "lesson_id": lesson.id,
                        "prerequisite_lesson_id": prerequisite.lesson_id,
                    }
                    for prerequisite in lesson.prerequisites
                ],
            )

    def _source_states_for_version(
        self,
        connection: Connection,
        version: CourseVersion,
    ) -> dict[str, BoundSourceState]:
        bound_version_ids = {
            binding.version_id
            for module in version.modules
            for lesson in module.lessons
            for binding in lesson.source_bindings
        }
        if not bound_version_ids:
            return {}
        version_rows = connection.execute(
            select(versions).where(versions.c.id.in_(sorted(bound_version_ids)))
        ).mappings().all()
        span_rows = connection.execute(
            select(spans.c.id, spans.c.version_id).where(
                spans.c.version_id.in_(sorted(bound_version_ids))
            )
        ).all()
        span_ids: dict[str, set[str]] = defaultdict(set)
        for span_id, source_version_id in span_rows:
            span_ids[str(source_version_id)].add(str(span_id))
        return {
            str(row["id"]): BoundSourceState(
                document_id=str(row["document_id"]),
                version_id=str(row["id"]),
                approved=row["review_state"] == "approved",
                evidence_span_ids=frozenset(span_ids[str(row["id"])]),
                effective_from=row["effective_from"],
                effective_until=row["effective_until"],
                rescinded_at=row["rescinded_at"],
            )
            for row in version_rows
        }

    @staticmethod
    def _load_version(connection: Connection, version_id: str) -> CourseVersion | None:
        version_row = connection.execute(
            select(learning_course_versions).where(learning_course_versions.c.id == version_id)
        ).mappings().first()
        if version_row is None:
            return None
        module_rows = connection.execute(
            select(learning_modules)
            .where(learning_modules.c.course_version_id == version_id)
            .order_by(learning_modules.c.ordinal, learning_modules.c.id)
        ).mappings().all()
        lesson_rows = connection.execute(
            select(learning_lessons)
            .where(learning_lessons.c.course_version_id == version_id)
            .order_by(
                learning_lessons.c.module_id,
                learning_lessons.c.ordinal,
                learning_lessons.c.id,
            )
        ).mappings().all()
        objective_rows = connection.execute(
            select(learning_objectives)
            .where(learning_objectives.c.course_version_id == version_id)
            .order_by(learning_objectives.c.lesson_id, learning_objectives.c.ordinal)
        ).mappings().all()
        binding_rows = connection.execute(
            select(learning_source_bindings).where(
                learning_source_bindings.c.course_version_id == version_id
            )
        ).mappings().all()
        span_rows = connection.execute(
            select(learning_source_binding_spans).where(
                learning_source_binding_spans.c.course_version_id == version_id
            )
        ).mappings().all()
        block_rows = connection.execute(
            select(learning_lesson_blocks)
            .where(learning_lesson_blocks.c.course_version_id == version_id)
            .order_by(learning_lesson_blocks.c.lesson_id, learning_lesson_blocks.c.ordinal)
        ).mappings().all()
        block_source_rows = connection.execute(
            select(learning_block_sources).where(
                learning_block_sources.c.course_version_id == version_id
            )
        ).mappings().all()
        prerequisite_rows = connection.execute(
            select(learning_prerequisites).where(
                learning_prerequisites.c.course_version_id == version_id
            )
        ).mappings().all()

        objectives: dict[str, list[LearningObjective]] = defaultdict(list)
        for row in objective_rows:
            objectives[row["lesson_id"]].append(
                LearningObjective(id=row["id"], statement=row["statement"])
            )
        binding_spans: dict[tuple[str, str], set[str]] = defaultdict(set)
        for row in span_rows:
            binding_spans[(row["lesson_id"], row["binding_id"])].add(row["span_id"])
        bindings: dict[str, list[SourceBinding]] = defaultdict(list)
        for row in binding_rows:
            bindings[row["lesson_id"]].append(
                SourceBinding(
                    id=row["id"],
                    document_id=row["document_id"],
                    version_id=row["version_id"],
                    evidence_span_ids=frozenset(
                        binding_spans[(row["lesson_id"], row["id"])]
                    ),
                )
            )
        block_sources: dict[tuple[str, str], set[str]] = defaultdict(set)
        for row in block_source_rows:
            block_sources[(row["lesson_id"], row["block_id"])].add(row["binding_id"])
        blocks: dict[str, list[LessonBlock]] = defaultdict(list)
        for row in block_rows:
            blocks[row["lesson_id"]].append(
                LessonBlock(
                    id=row["id"],
                    ordinal=row["ordinal"],
                    kind=LessonBlockKind(row["kind"]),
                    title=row["title"],
                    source_binding_ids=frozenset(
                        block_sources[(row["lesson_id"], row["id"])]
                    ),
                )
            )
        prerequisites: dict[str, list[Prerequisite]] = defaultdict(list)
        for row in prerequisite_rows:
            prerequisites[row["lesson_id"]].append(
                Prerequisite(lesson_id=row["prerequisite_lesson_id"])
            )
        lessons: dict[str, list[Lesson]] = defaultdict(list)
        for row in lesson_rows:
            lessons[row["module_id"]].append(
                Lesson(
                    id=row["id"],
                    ordinal=row["ordinal"],
                    title=row["title"],
                    objectives=tuple(objectives[row["id"]]),
                    source_bindings=tuple(bindings[row["id"]]),
                    blocks=tuple(blocks[row["id"]]),
                    prerequisites=tuple(prerequisites[row["id"]]),
                )
            )
        modules = tuple(
            CourseModule(
                id=row["id"],
                ordinal=row["ordinal"],
                title=row["title"],
                lessons=tuple(lessons[row["id"]]),
            )
            for row in module_rows
        )
        return CourseVersion(
            id=version_row["id"],
            course_id=version_row["course_id"],
            revision=version_row["revision"],
            modules=modules,
        )
