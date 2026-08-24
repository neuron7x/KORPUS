"""Transactional persistence for deterministic learner mastery state."""
from __future__ import annotations

import json
from datetime import UTC

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Engine

from korpus.application.training_progression import LearnerProgress, ObjectiveMastery, ObjectiveState
from korpus.infrastructure.learning_schema import learning_course_versions, learning_mastery


class SqlTrainingProgressRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save(self, progress: LearnerProgress) -> None:
        """Atomically replace one learner/course projection; canonical sources stay elsewhere."""
        with self.engine.begin() as connection:
            exists = connection.execute(
                select(learning_course_versions.c.id).where(
                    learning_course_versions.c.id == progress.course_version_id
                )
            ).scalar_one_or_none()
            if exists is None:
                raise LookupError(f"course version not found: {progress.course_version_id}")
            connection.execute(
                delete(learning_mastery).where(
                    learning_mastery.c.subject == progress.subject,
                    learning_mastery.c.course_version_id == progress.course_version_id,
                )
            )
            if progress.mastery:
                connection.execute(
                    insert(learning_mastery),
                    [
                        {
                            "subject": progress.subject,
                            "course_version_id": progress.course_version_id,
                            "objective_id": item.objective_id,
                            "state": item.state.value,
                            "last_check_id": item.last_check_id,
                            "source_binding_ids": json.dumps(list(item.source_binding_ids), separators=(",", ":")),
                            "updated_at": item.updated_at,
                        }
                        for item in progress.mastery
                    ],
                )

    def load(self, subject: str, course_version_id: str) -> LearnerProgress:
        with self.engine.connect() as connection:
            exists = connection.execute(
                select(learning_course_versions.c.id).where(
                    learning_course_versions.c.id == course_version_id
                )
            ).scalar_one_or_none()
            if exists is None:
                raise LookupError(f"course version not found: {course_version_id}")
            rows = connection.execute(
                select(learning_mastery)
                .where(
                    learning_mastery.c.subject == subject,
                    learning_mastery.c.course_version_id == course_version_id,
                )
                .order_by(learning_mastery.c.objective_id)
            ).mappings().all()
        mastery = []
        for row in rows:
            stamp = row["updated_at"]
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            mastery.append(
                ObjectiveMastery(
                    objective_id=str(row["objective_id"]),
                    state=ObjectiveState(str(row["state"])),
                    last_check_id=row["last_check_id"],
                    source_binding_ids=tuple(json.loads(str(row["source_binding_ids"]))),
                    updated_at=stamp,
                )
            )
        return LearnerProgress(
            subject=subject,
            course_version_id=course_version_id,
            mastery=tuple(mastery),
        )
