"""Authorized publication of one persisted learning graph in one transaction."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from korpus.domain.learning import (
    CoursePublication,
    CoursePublicationState,
    validate_course_publication,
)
from korpus.domain.models import Identity
from korpus.infrastructure.learning_schema import learning_publications
from korpus.infrastructure.learning_source_access import LearningSourceAccess
from korpus.infrastructure.learning_version_reader import load_course_version


class LearningStateError(RuntimeError):
    """A requested transition violates an immutable learning lifecycle invariant."""


class LearningPublicationWriter:
    """Publication transaction shared by the public learning persistence adapter."""

    engine: Engine
    _sources: LearningSourceAccess

    def publish_version(
        self,
        version_id: str,
        *,
        reviewed_by: str,
        reviewed_at: datetime | None = None,
        as_of: date | None = None,
        identity: Identity | None = None,
    ) -> CoursePublication:
        reviewer = reviewed_by.strip()
        if not reviewer:
            raise ValueError("reviewed_by must be non-empty")
        stamp = reviewed_at or datetime.now(UTC)
        with self.engine.begin() as connection:
            self._sources.bind(connection, identity)
            publication = (
                connection.execute(
                    select(learning_publications)
                    .where(learning_publications.c.course_version_id == version_id)
                    .with_for_update()
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
                self._sources.load(connection, version, identity),
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
