from __future__ import annotations

from pathlib import Path

import pytest
from korpus.domain.operational_competency import (
    Competency,
    CompetencyFramework,
    OperationalRole,
    OperationalTask,
)
from korpus.infrastructure.competency_repository import (
    CompetencyPersistenceError,
    SqlCompetencyRepository,
)
from korpus.infrastructure.repository import SqlRepository


def _framework(*, revision: str = "1") -> CompetencyFramework:
    return CompetencyFramework(
        id="framework.medical",
        revision=revision,
        roles=(OperationalRole(id="role.medic", title="Combat medic", task_ids={"task.assess"}),),
        tasks=(
            OperationalTask(
                id="task.assess",
                statement="Assess a casualty",
                conditions="Under the approved training scenario",
                standard="Complete every required assessment step",
                competency_ids={"competency.safety", "competency.sequence"},
            ),
        ),
        competencies=(
            Competency(id="competency.safety", statement="Apply the safety check"),
            Competency(id="competency.sequence", statement="Use the approved sequence"),
        ),
    )


@pytest.fixture
def repository(tmp_path: Path) -> SqlCompetencyRepository:
    root = SqlRepository(
        f"sqlite:///{tmp_path / 'competency.db'}",
        "audit-key",
        audit_anchor_path=tmp_path / "anchor.json",
    )
    root.initialize()
    return SqlCompetencyRepository(root.engine)


def test_framework_revision_round_trip_is_exact(repository: SqlCompetencyRepository) -> None:
    framework = _framework()
    repository.create(framework)
    assert repository.get(framework.id, framework.revision) == framework


def test_framework_revisions_are_independent(repository: SqlCompetencyRepository) -> None:
    first = _framework(revision="1")
    second = _framework(revision="2")
    repository.create(first)
    repository.create(second)
    assert repository.get(first.id, first.revision) == first
    assert repository.get(second.id, second.revision) == second


def test_duplicate_framework_revision_is_refused_atomically(
    repository: SqlCompetencyRepository,
) -> None:
    framework = _framework()
    repository.create(framework)
    with pytest.raises(CompetencyPersistenceError, match="persistence constraints"):
        repository.create(framework)
    assert repository.get(framework.id, framework.revision) == framework


def test_unknown_framework_revision_is_none(repository: SqlCompetencyRepository) -> None:
    assert repository.get("missing", "1") is None
