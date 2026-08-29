"""Transactional persistence for immutable competency framework revisions."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from korpus.domain.operational_competency import (
    Competency,
    CompetencyFramework,
    OperationalRole,
    OperationalTask,
)
from korpus.infrastructure.competency_schema import (
    competency_frameworks,
    operational_competencies,
    operational_role_tasks,
    operational_roles,
    operational_task_competencies,
    operational_tasks,
)


class CompetencyPersistenceError(RuntimeError):
    """A framework revision conflicts with immutable persisted state."""


class SqlCompetencyRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create(
        self,
        framework: CompetencyFramework,
        *,
        created_at: datetime | None = None,
    ) -> None:
        stamp = created_at or datetime.now(UTC)
        identity = {
            "framework_id": framework.id,
            "framework_revision": framework.revision,
        }
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(competency_frameworks).values(
                        id=framework.id, revision=framework.revision, created_at=stamp
                    )
                )
                connection.execute(
                    insert(operational_roles),
                    [identity | role.model_dump(exclude={"task_ids"}) for role in framework.roles],
                )
                connection.execute(
                    insert(operational_tasks),
                    [
                        identity | task.model_dump(exclude={"competency_ids"})
                        for task in framework.tasks
                    ],
                )
                connection.execute(
                    insert(operational_competencies),
                    [identity | competency.model_dump() for competency in framework.competencies],
                )
                connection.execute(
                    insert(operational_role_tasks),
                    [
                        identity | {"role_id": role.id, "task_id": task_id}
                        for role in framework.roles
                        for task_id in sorted(role.task_ids)
                    ],
                )
                connection.execute(
                    insert(operational_task_competencies),
                    [
                        identity | {"task_id": task.id, "competency_id": competency_id}
                        for task in framework.tasks
                        for competency_id in sorted(task.competency_ids)
                    ],
                )
        except IntegrityError as exc:
            raise CompetencyPersistenceError(
                "competency framework revision violates persistence constraints"
            ) from exc

    def get(self, framework_id: str, revision: str) -> CompetencyFramework | None:
        key = (
            competency_frameworks.c.id == framework_id,
            competency_frameworks.c.revision == revision,
        )
        with self.engine.connect() as connection:
            if connection.execute(select(competency_frameworks).where(*key)).first() is None:
                return None
            roles = (
                connection.execute(
                    select(operational_roles)
                    .where(
                        operational_roles.c.framework_id == framework_id,
                        operational_roles.c.framework_revision == revision,
                    )
                    .order_by(operational_roles.c.id)
                )
                .mappings()
                .all()
            )
            tasks = (
                connection.execute(
                    select(operational_tasks)
                    .where(
                        operational_tasks.c.framework_id == framework_id,
                        operational_tasks.c.framework_revision == revision,
                    )
                    .order_by(operational_tasks.c.id)
                )
                .mappings()
                .all()
            )
            competencies = (
                connection.execute(
                    select(operational_competencies)
                    .where(
                        operational_competencies.c.framework_id == framework_id,
                        operational_competencies.c.framework_revision == revision,
                    )
                    .order_by(operational_competencies.c.id)
                )
                .mappings()
                .all()
            )
            role_edges = (
                connection.execute(
                    select(operational_role_tasks)
                    .where(
                        operational_role_tasks.c.framework_id == framework_id,
                        operational_role_tasks.c.framework_revision == revision,
                    )
                    .order_by(operational_role_tasks.c.role_id, operational_role_tasks.c.task_id)
                )
                .mappings()
                .all()
            )
            task_edges = (
                connection.execute(
                    select(operational_task_competencies)
                    .where(
                        operational_task_competencies.c.framework_id == framework_id,
                        operational_task_competencies.c.framework_revision == revision,
                    )
                    .order_by(
                        operational_task_competencies.c.task_id,
                        operational_task_competencies.c.competency_id,
                    )
                )
                .mappings()
                .all()
            )

        tasks_by_role: dict[str, set[str]] = defaultdict(set)
        for row in role_edges:
            tasks_by_role[str(row["role_id"])].add(str(row["task_id"]))
        competencies_by_task: dict[str, set[str]] = defaultdict(set)
        for row in task_edges:
            competencies_by_task[str(row["task_id"])].add(str(row["competency_id"]))
        return CompetencyFramework(
            id=framework_id,
            revision=revision,
            roles=tuple(
                OperationalRole(
                    id=str(row["id"]),
                    title=str(row["title"]),
                    task_ids=frozenset(tasks_by_role[str(row["id"])]),
                )
                for row in roles
            ),
            tasks=tuple(
                OperationalTask(
                    id=str(row["id"]),
                    statement=str(row["statement"]),
                    conditions=str(row["conditions"]),
                    standard=str(row["standard"]),
                    competency_ids=frozenset(competencies_by_task[str(row["id"])]),
                )
                for row in tasks
            ),
            competencies=tuple(
                Competency(id=str(row["id"]), statement=str(row["statement"]))
                for row in competencies
            ),
        )
