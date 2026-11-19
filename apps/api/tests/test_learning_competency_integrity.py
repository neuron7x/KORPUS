"""Published graph edges must survive hostile DML on either supported dialect."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from korpus.domain.learning import Course, CourseVersion
from korpus.domain.models import Identity
from korpus.domain.operational_competency import (
    Competency,
    CompetencyFramework,
    OperationalRole,
    OperationalTask,
)
from korpus.infrastructure.competency_repository import SqlCompetencyRepository
from korpus.infrastructure.learning_repository import SqlLearningRepository
from korpus.infrastructure.migration_admission import MigrationAdmissionError
from korpus.infrastructure.repository import SqlRepository
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from apps.api.tests.learning_postgres_support import (
    OTHER_SOURCE,
    SOURCE,
    LearningPostgres,
    _seed_source,
    course_graph,
)
from apps.api.tests.learning_postgres_support import learning_postgres as learning_postgres
from apps.api.tests.test_learning_repository import _source, _version
from apps.api.tests.test_migration_admission_policy import _configuration, _dump


@dataclass(frozen=True)
class CompetencyStore:
    engine: Engine
    learning: SqlLearningRepository
    identity: Identity | None
    graph: CourseVersion
    draft: CourseVersion
    today: date


def _framework() -> CompetencyFramework:
    return CompetencyFramework(
        id="public-library",
        revision="1",
        roles=(OperationalRole(id="librarian", title="Librarian", task_ids={"lookup"}),),
        tasks=(
            OperationalTask(
                id="lookup",
                statement="Find a public catalog record",
                conditions="Public catalog fixture",
                standard="Match the record",
                competency_ids={"catalog", "citation"},
            ),
        ),
        competencies=(
            Competency(id="catalog", statement="Identify catalog fields"),
            Competency(id="citation", statement="Identify citation fields"),
        ),
    )


def _bind_competencies(graph: CourseVersion) -> CourseVersion:
    payload = graph.model_dump()
    payload.update(competency_framework_id="public-library", competency_framework_revision="1")
    for module in payload["modules"]:
        for lesson in module["lessons"]:
            for objective in lesson["objectives"]:
                objective["competency_ids"] = {"catalog"}
    return CourseVersion.model_validate(payload)


@pytest.fixture(
    params=["sqlite", "sqlite-migrated", pytest.param("postgres", marks=pytest.mark.postgres)]
)
def competency_store(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[CompetencyStore]:
    canonical: SqlRepository | None = None
    if request.param == "postgres":
        postgres: LearningPostgres = request.getfixturevalue("learning_postgres")
        engine, learning = postgres.app, postgres.learning
        graph, identity, today = course_graph(), postgres.identity, postgres.today
    else:
        database_url = f"sqlite:///{tmp_path / 'competencies.db'}"
        migrated = request.param == "sqlite-migrated"
        if migrated:
            _, config = _configuration(tmp_path)
            monkeypatch.setenv("KORPUS_DATABASE_URL", database_url)
            command.upgrade(config, "head")
        canonical = SqlRepository(
            database_url,
            "public-fixture-key",
            audit_anchor_path=tmp_path / "anchor.json",
        )
        canonical.initialize(create_schema=not migrated)
        engine = canonical.engine
        learning = SqlLearningRepository(engine)
        identity, today = None, date(2026, 8, 16)
        if migrated:
            _seed_source(engine, SOURCE, today)
            _seed_source(engine, OTHER_SOURCE, today)
            graph = course_graph()
        else:
            _source(canonical)
            graph = _version()
        learning.create_course(Course(id=graph.course_id, specialty_id="public", title="Library"))
    try:
        SqlCompetencyRepository(engine).create(_framework())
        graph = _bind_competencies(graph)
        draft = graph.model_copy(update={"id": "draft-v2", "revision": "2"})
        learning.create_version(graph)
        learning.create_version(draft)
        yield CompetencyStore(engine, learning, identity, graph, draft, today)
    finally:
        if canonical is not None:
            canonical.close()


def _statement(store: CompetencyStore, operation: str) -> tuple[str, dict[str, str]]:
    lesson = store.graph.modules[0].lessons[0]
    parameters = {
        "version": store.graph.id,
        "draft": store.draft.id,
        "lesson": lesson.id,
        "objective": lesson.objectives[0].id,
    }
    where = " WHERE course_version_id=:version AND lesson_id=:lesson AND objective_id=:objective"
    statements = {
        "insert": (
            "INSERT INTO learning_objective_competencies "
            "(course_version_id,lesson_id,objective_id,competency_id) "
            "VALUES (:version,:lesson,:objective,'citation')"
        ),
        "update": "UPDATE learning_objective_competencies SET competency_id='citation'" + where,
        "delete": "DELETE FROM learning_objective_competencies" + where,
        "move-out": (
            "UPDATE learning_objective_competencies "
            "SET course_version_id=:draft,competency_id='citation'" + where
        ),
        "move-in": (
            "UPDATE learning_objective_competencies "
            "SET course_version_id=:version,competency_id='citation'"
            " WHERE course_version_id=:draft AND lesson_id=:lesson AND objective_id=:objective"
        ),
    }
    return statements[operation], parameters


@pytest.mark.parametrize("state", ["published", "invalidated", "retired"])
@pytest.mark.parametrize("operation", ["insert", "update", "delete", "move-out", "move-in"])
def test_published_competency_edges_refuse_application_dml(
    competency_store: CompetencyStore, state: str, operation: str
) -> None:
    store = competency_store
    store.learning.publish_version(
        store.graph.id,
        reviewed_by="public-library-reviewer",
        as_of=store.today,
        identity=store.identity,
    )
    if state != "published":
        with store.engine.begin() as connection:
            connection.execute(
                text("UPDATE learning_publications SET state=:state WHERE course_version_id=:id"),
                {"state": state, "id": store.graph.id},
            )
    before = store.learning.get_publication(store.graph.id)
    statement, parameters = _statement(store, operation)
    with (
        pytest.raises(DBAPIError, match="immutable") as failure,
        store.engine.begin() as connection,
    ):
        connection.execute(text(statement), parameters)
    if store.engine.dialect.name == "postgresql":
        assert getattr(failure.value.orig, "sqlstate", None) == "42501"
    assert store.learning.get_publication(store.graph.id) == before
    assert store.learning.get_version(store.graph.id) == store.graph
    assert store.learning.get_version(store.draft.id) == store.draft


@pytest.mark.parametrize("operation", ["insert", "update", "delete", "move-out", "move-in"])
def test_draft_competency_edges_remain_mutable(
    competency_store: CompetencyStore, operation: str
) -> None:
    store = competency_store
    statement, parameters = _statement(store, operation)
    with store.engine.begin() as connection:
        assert connection.execute(text(statement), parameters).rowcount == 1
    assert store.learning.get_version(store.graph.id) != store.graph


def test_new_course_revision_publishes_without_rewriting_competency_history(
    competency_store: CompetencyStore,
) -> None:
    store = competency_store
    for graph in (store.graph, store.draft):
        store.learning.publish_version(
            graph.id,
            reviewed_by="public-library-reviewer",
            as_of=store.today,
            identity=store.identity,
        )
        assert store.learning.get_version(graph.id) == graph
    assert store.learning.get_version(store.graph.id) == store.graph


def test_competency_forward_migration_preserves_retirement_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, config = _configuration(tmp_path)
    database = tmp_path / "previous.db"
    monkeypatch.setenv("KORPUS_DATABASE_URL", f"sqlite:///{database}")
    command.upgrade(config, "0026_learning_history_integrity")
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND tbl_name='learning_objective_competencies'"
            ).fetchall()
            == []
        )
        connection.execute("CREATE TABLE prior_history(value TEXT)")
        connection.execute("INSERT INTO prior_history VALUES ('preserve')")
    before = _dump(database)
    with pytest.raises(MigrationAdmissionError, match="DENIED_RETIREMENT_UNPROVEN"):
        command.upgrade(config, "head")
    assert _dump(database) == before
