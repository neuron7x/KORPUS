"""Transactional persistence adapter for immutable learning course graphs."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from korpus.domain.learning import (
    Course,
    CoursePublication,
    CoursePublicationState,
    CourseVersion,
    PublicationValidation,
    validate_course_publication,
)
from korpus.infrastructure.competency_schema import (
    competency_frameworks,
    operational_competencies,
)
from korpus.infrastructure.learning_schema import (
    learning_course_versions,
    learning_courses,
    learning_publications,
)
from korpus.infrastructure.learning_source_state import load_bound_source_states
from korpus.infrastructure.learning_version_reader import load_course_version
from korpus.infrastructure.learning_version_writer import insert_course_version


class LearningStateError(RuntimeError):
    """A requested transition violates an immutable learning lifecycle invariant."""


class SqlLearningRepository:
    """Persist course graphs without copying canonical corpus text into learning tables."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_course(self, course: Course, *, created_at: datetime | None = None) -> None:
        stamp = created_at or datetime.now(UTC)
        with self.engine.begin() as connection:
            connection.execute(
                insert(learning_courses).values(
                    id=course.id,
                    specialty_id=course.specialty_id,
                    title=course.title,
                    created_at=stamp,
                )
            )

    def get_course(self, course_id: str) -> Course | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(learning_courses).where(learning_courses.c.id == course_id)
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return Course(
            id=str(row["id"]),
            specialty_id=str(row["specialty_id"]),
            title=str(row["title"]),
        )

    def create_version(
        self,
        version: CourseVersion,
        *,
        created_at: datetime | None = None,
    ) -> None:
        stamp = created_at or datetime.now(UTC)
        with self.engine.begin() as connection:
            course_exists = connection.execute(
                select(learning_courses.c.id).where(learning_courses.c.id == version.course_id)
            ).scalar_one_or_none()
            if course_exists is None:
                raise LookupError(f"course not found: {version.course_id}")
            if version.competency_framework_id is not None:
                framework_key = (
                    competency_frameworks.c.id == version.competency_framework_id,
                    competency_frameworks.c.revision == version.competency_framework_revision,
                )
                if (
                    connection.execute(
                        select(competency_frameworks.c.id).where(*framework_key)
                    ).scalar_one_or_none()
                    is None
                ):
                    raise LearningStateError("competency framework revision not found")
                known_competencies = set(
                    connection.execute(
                        select(operational_competencies.c.id).where(
                            operational_competencies.c.framework_id
                            == version.competency_framework_id,
                            operational_competencies.c.framework_revision
                            == version.competency_framework_revision,
                        )
                    ).scalars()
                )
                requested_competencies = {
                    competency_id
                    for module in version.modules
                    for lesson in module.lessons
                    for objective in lesson.objectives
                    for competency_id in objective.competency_ids
                }
                unknown_competencies = requested_competencies - known_competencies
                if unknown_competencies:
                    raise LearningStateError(
                        "course objective references unknown framework competencies: "
                        + ", ".join(sorted(unknown_competencies))
                    )
            try:
                insert_course_version(connection, version, stamp)
            except IntegrityError as exc:
                raise LearningStateError(
                    "course version violates learning persistence constraints"
                ) from exc

    def get_version(self, version_id: str) -> CourseVersion | None:
        with self.engine.connect() as connection:
            return load_course_version(connection, version_id)

    def get_publication(self, version_id: str) -> CoursePublication | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(learning_publications).where(
                        learning_publications.c.course_version_id == version_id
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        reviewed_at = row["reviewed_at"]
        if reviewed_at is not None and reviewed_at.tzinfo is None:
            reviewed_at = reviewed_at.replace(tzinfo=UTC)
        return CoursePublication(
            course_version_id=version_id,
            state=CoursePublicationState(str(row["state"])),
            reviewed_at=reviewed_at,
            reviewed_by=row["reviewed_by"],
        )

    def validate_version(
        self,
        version_id: str,
        *,
        as_of: date | None = None,
    ) -> PublicationValidation:
        with self.engine.connect() as connection:
            version = load_course_version(connection, version_id)
            if version is None:
                raise LookupError(f"course version not found: {version_id}")
            states = load_bound_source_states(connection, version)
        return validate_course_publication(version, states, as_of=as_of)

    def get_serving_version(
        self,
        version_id: str,
        *,
        as_of: date | None = None,
    ) -> CourseVersion:
        """Return only currently source-valid published content; otherwise invalidate it."""

        invalidation_reason: str | None = None
        with self.engine.begin() as connection:
            state = connection.execute(
                select(learning_publications.c.state).where(
                    learning_publications.c.course_version_id == version_id
                )
            ).scalar_one_or_none()
            if state is None:
                raise LookupError(f"course version not found: {version_id}")
            if str(state) != CoursePublicationState.PUBLISHED.value:
                raise LearningStateError(f"course version is not serving from state {state}")
            version = load_course_version(connection, version_id)
            if version is None:
                raise LookupError(f"course version not found: {version_id}")
            validation = validate_course_publication(
                version,
                load_bound_source_states(connection, version),
                as_of=as_of,
            )
            if not validation.publishable:
                invalidation_reason = ", ".join(validation.violations)
                connection.execute(
                    update(learning_publications)
                    .where(learning_publications.c.course_version_id == version_id)
                    .values(
                        state=CoursePublicationState.INVALIDATED.value,
                        updated_at=datetime.now(UTC),
                    )
                )
        if invalidation_reason is not None:
            raise LearningStateError(
                "published learning content is no longer source-valid: " + invalidation_reason
            )
        return version

    def publish_version(
        self,
        version_id: str,
        *,
        reviewed_by: str,
        reviewed_at: datetime | None = None,
        as_of: date | None = None,
    ) -> CoursePublication:
        reviewer = reviewed_by.strip()
        if not reviewer:
            raise ValueError("reviewed_by must be non-empty")
        stamp = reviewed_at or datetime.now(UTC)
        with self.engine.begin() as connection:
            publication = (
                connection.execute(
                    select(learning_publications).where(
                        learning_publications.c.course_version_id == version_id
                    )
                )
                .mappings()
                .first()
            )
            if publication is None:
                raise LookupError(f"course version not found: {version_id}")
            if str(publication["state"]) != CoursePublicationState.DRAFT.value:
                raise LearningStateError(
                    f"course version is not publishable from state {publication['state']}"
                )
            version = load_course_version(connection, version_id)
            if version is None:
                raise LookupError(f"course version not found: {version_id}")
            validation = validate_course_publication(
                version,
                load_bound_source_states(connection, version),
                as_of=as_of,
            )
            if not validation.publishable:
                raise LearningStateError(
                    "learning publication blocked: " + ", ".join(validation.violations)
                )
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

    def retire_version(
        self,
        version_id: str,
        *,
        retired_at: datetime | None = None,
    ) -> CoursePublication:
        stamp = retired_at or datetime.now(UTC)
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(learning_publications).where(
                        learning_publications.c.course_version_id == version_id
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise LookupError(f"course version not found: {version_id}")
            if str(row["state"]) not in {
                CoursePublicationState.PUBLISHED.value,
                CoursePublicationState.INVALIDATED.value,
            }:
                raise LearningStateError(f"cannot retire learning state {row['state']}")
            connection.execute(
                update(learning_publications)
                .where(learning_publications.c.course_version_id == version_id)
                .values(state=CoursePublicationState.RETIRED.value, updated_at=stamp)
            )
            reviewed_at = row["reviewed_at"]
            if reviewed_at is not None and reviewed_at.tzinfo is None:
                reviewed_at = reviewed_at.replace(tzinfo=UTC)
        return CoursePublication(
            course_version_id=version_id,
            state=CoursePublicationState.RETIRED,
            reviewed_at=reviewed_at,
            reviewed_by=row["reviewed_by"],
        )

    def delete_draft_version(self, version_id: str) -> bool:
        """Delete only never-published draft content; historical versions are immutable."""

        with self.engine.begin() as connection:
            state = connection.execute(
                select(learning_publications.c.state).where(
                    learning_publications.c.course_version_id == version_id
                )
            ).scalar_one_or_none()
            if state is None:
                return False
            if str(state) != CoursePublicationState.DRAFT.value:
                raise LearningStateError("published learning history cannot be deleted")
            connection.execute(
                delete(learning_publications).where(
                    learning_publications.c.course_version_id == version_id
                )
            )
            result = connection.execute(
                delete(learning_course_versions).where(learning_course_versions.c.id == version_id)
            )
            return bool(result.rowcount)
