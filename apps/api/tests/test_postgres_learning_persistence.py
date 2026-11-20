"""Issue #100 / #35: named, real-PostgreSQL publication and immutability controls.

These tests intentionally exercise both the authorized repository entry point and
direct application SQL. They must not acquire owner privileges to make a positive
publication pass. The existing SQLite repository tests remain a separate proof.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from korpus.domain.learning import CoursePublicationState, Prerequisite
from korpus.infrastructure.learning_repository import LearningStateError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from apps.api.tests.learning_postgres_support import (
    MISSING_ID,
    OTHER_SOURCE,
    LearningPostgres,
    course_graph,
    publish_sql,
    reject_sql,
    set_source_fixture_state,
)
from apps.api.tests.learning_postgres_support import (
    learning_postgres as learning_postgres,
)

pytestmark = pytest.mark.postgres


def test_postgres_learning_repository_publishes_valid_exact_source_graph(
    learning_postgres: LearningPostgres,
) -> None:
    store = learning_postgres
    graph = course_graph()
    store.learning.create_version(graph)
    assert store.learning.get_version(graph.id) == graph
    validation = store.learning.validate_version(
        graph.id, as_of=store.today, identity=store.identity
    )
    assert validation.publishable, validation.violations
    publication = store.learning.publish_version(
        graph.id, reviewed_by="public-course-reviewer", as_of=store.today, identity=store.identity
    )
    assert publication.state is CoursePublicationState.PUBLISHED
    assert (
        store.learning.get_serving_version(graph.id, as_of=store.today, identity=store.identity)
        == graph
    )


def test_postgres_learning_sql_publication_and_new_revision_keep_exact_bindings(
    learning_postgres: LearningPostgres,
) -> None:
    store = learning_postgres
    first, second = course_graph(), course_graph(revision="2")
    for graph in (first, second):
        store.learning.create_version(graph)
        publish_sql(store, graph.id)
        assert store.learning.get_version(graph.id) == graph
        publication = store.learning.get_publication(graph.id)
        assert publication is not None and publication.state is CoursePublicationState.PUBLISHED
    assert store.learning.get_version(first.id) == first
    with store.app.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM learning_course_versions WHERE course_id = 'library'")
            ).scalar_one()
            == 2
        )


def test_postgres_learning_rejects_cyclic_publication(learning_postgres: LearningPostgres) -> None:
    store = learning_postgres
    graph = course_graph()
    module = graph.modules[0]
    first = module.lessons[0].model_copy(
        update={"prerequisites": (Prerequisite(lesson_id="citations"),)}
    )
    cyclic = graph.model_copy(
        update={"modules": (module.model_copy(update={"lessons": (first, module.lessons[1])}),)}
    )
    store.learning.create_version(cyclic)
    with pytest.raises(DBAPIError, match="prerequisite graph contains a cycle") as failure:
        publish_sql(store, graph.id)
    assert getattr(failure.value.orig, "sqlstate", None) == "23514"
    publication = store.learning.get_publication(graph.id)
    assert publication is not None and publication.state is CoursePublicationState.DRAFT


def test_postgres_learning_rejects_dangling_prerequisite_atomically(
    learning_postgres: LearningPostgres,
) -> None:
    store = learning_postgres
    graph = course_graph()
    module = graph.modules[0]
    first = module.lessons[0].model_copy(
        update={"prerequisites": (Prerequisite(lesson_id="missing"),)}
    )
    dangling = graph.model_copy(
        update={"modules": (module.model_copy(update={"lessons": (first, module.lessons[1])}),)}
    )
    with pytest.raises(LearningStateError, match="persistence constraints") as failure:
        store.learning.create_version(dangling)
    assert isinstance(failure.value.__cause__, IntegrityError)
    assert getattr(failure.value.__cause__.orig, "sqlstate", None) == "23503"
    assert store.learning.get_version(graph.id) is None
    assert store.learning.get_publication(graph.id) is None


@pytest.mark.parametrize(
    "binding_changes",
    [{"version_id": MISSING_ID}, {"evidence_span_ids": frozenset({MISSING_ID})}],
    ids=["unknown-version", "unknown-span"],
)
def test_postgres_learning_rejects_unknown_source_reference_atomically(
    learning_postgres: LearningPostgres, binding_changes: dict[str, object]
) -> None:
    store = learning_postgres
    graph = course_graph(binding_changes=binding_changes)
    with pytest.raises(LearningStateError, match="persistence constraints") as failure:
        store.learning.create_version(graph)
    assert isinstance(failure.value.__cause__, IntegrityError)
    assert getattr(failure.value.__cause__.orig, "sqlstate", None) == "23503"
    assert store.learning.get_version(graph.id) is None
    assert store.learning.get_publication(graph.id) is None


@pytest.mark.parametrize(
    "case",
    ["unapproved", "rescinded", "expired", "future", "document-mismatch", "span-mismatch"],
)
def test_postgres_learning_sql_publication_rejects_invalid_source(
    learning_postgres: LearningPostgres, case: str
) -> None:
    store = learning_postgres
    source_changes = {
        "unapproved": {"review_state": "quarantined", "is_current": False},
        "rescinded": {"rescinded_at": datetime.now(UTC)},
        "expired": {"effective_until": store.today - timedelta(days=1)},
        "future": {"effective_from": store.today + timedelta(days=1)},
    }
    binding_changes = {
        "document-mismatch": {"document_id": str(OTHER_SOURCE[0])},
        "span-mismatch": {"evidence_span_ids": frozenset({str(OTHER_SOURCE[2])})},
    }
    if case in source_changes:
        set_source_fixture_state(store, **source_changes[case])
    graph = course_graph(binding_changes=binding_changes.get(case))
    store.learning.create_version(graph)
    message = (
        "evidence span does not belong"
        if case == "span-mismatch"
        else "source is not approved and effective"
    )
    with pytest.raises(DBAPIError, match=message) as failure:
        publish_sql(store, graph.id)
    assert getattr(failure.value.orig, "sqlstate", None) == "23514"
    publication = store.learning.get_publication(graph.id)
    assert publication is not None and publication.state is CoursePublicationState.DRAFT
    assert store.learning.get_version(graph.id) == graph


def test_postgres_learning_sql_publication_rejects_unbound_block(
    learning_postgres: LearningPostgres,
) -> None:
    store = learning_postgres
    graph = course_graph()
    store.learning.create_version(graph)
    with store.app.begin() as connection:
        assert (
            connection.execute(
                text(
                    "DELETE FROM learning_block_sources WHERE course_version_id = 'library-v1' AND lesson_id = 'catalog'"
                )
            ).rowcount
            == 1
        )
    with pytest.raises(DBAPIError, match="block requires an exact source binding") as failure:
        publish_sql(store, graph.id)
    assert getattr(failure.value.orig, "sqlstate", None) == "23514"


CONTENT_UPDATES = {
    "learning_courses": "title = 'Changed library title'",
    "learning_course_versions": "revision = 'changed'",
    "learning_modules": "title = 'Changed module title'",
    "learning_lessons": "title = 'Changed lesson title'",
    "learning_objectives": "statement = 'Changed learning objective'",
    "learning_source_bindings": f"document_id = '{OTHER_SOURCE[0]}', version_id = '{OTHER_SOURCE[1]}'",
    "learning_source_binding_spans": f"span_id = '{OTHER_SOURCE[2]}'",
    "learning_lesson_blocks": "title = 'Changed block title'",
    "learning_block_sources": "binding_id = 'alternate-source'",
    "learning_prerequisites": "lesson_id = 'catalog', prerequisite_lesson_id = 'citations'",
}


@pytest.mark.parametrize("table", CONTENT_UPDATES)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_postgres_learning_published_content_is_immutable_under_application_sql(
    learning_postgres: LearningPostgres, table: str, operation: str
) -> None:
    store = learning_postgres
    graph = course_graph()
    store.learning.create_version(graph)
    publish_sql(store, graph.id)
    before = store.learning.get_version(graph.id)
    with store.app.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() > 0
    sql = (
        f"UPDATE {table} SET {CONTENT_UPDATES[table]}"
        if operation == "UPDATE"
        else f"DELETE FROM {table}"
    )
    reject_sql(store, sql, sqlstate="42501", message="immutable")
    assert store.learning.get_version(graph.id) == before == graph


def test_postgres_learning_published_graph_rejects_new_content(
    learning_postgres: LearningPostgres,
) -> None:
    store = learning_postgres
    graph = course_graph()
    store.learning.create_version(graph)
    publish_sql(store, graph.id)
    reject_sql(
        store,
        "INSERT INTO learning_objectives(course_version_id, lesson_id, id, statement) "
        "VALUES ('library-v1', 'catalog', 'new-objective', 'A new learning objective')",
        sqlstate="42501",
        message="immutable",
    )
    assert store.learning.get_version(graph.id) == graph


def test_postgres_learning_published_lifecycle_row_cannot_be_deleted(
    learning_postgres: LearningPostgres,
) -> None:
    store = learning_postgres
    graph = course_graph()
    store.learning.create_version(graph)
    publish_sql(store, graph.id)
    before = store.learning.get_publication(graph.id)
    reject_sql(
        store,
        "DELETE FROM learning_publications WHERE course_version_id = 'library-v1'",
        sqlstate="42501",
        message="immutable",
    )
    assert store.learning.get_publication(graph.id) == before
    assert store.learning.get_version(graph.id) == graph


def test_postgres_learning_published_source_relation_cannot_move_to_draft(
    learning_postgres: LearningPostgres,
) -> None:
    store = learning_postgres
    published, draft = course_graph(), course_graph(revision="2")
    store.learning.create_version(published)
    publish_sql(store, published.id)
    store.learning.create_version(draft)
    with store.app.begin() as connection:
        assert (
            connection.execute(
                text(
                    "DELETE FROM learning_block_sources WHERE course_version_id = 'library-v2' AND lesson_id = 'catalog'"
                )
            ).rowcount
            == 1
        )
    reject_sql(
        store,
        "UPDATE learning_block_sources SET course_version_id = 'library-v2' "
        "WHERE course_version_id = 'library-v1' AND lesson_id = 'catalog'",
        sqlstate="42501",
        message="immutable",
    )
    assert store.learning.get_version(published.id) == published


def test_postgres_learning_source_transition_invalidates_serving_without_rewriting_history(
    learning_postgres: LearningPostgres,
) -> None:
    store = learning_postgres
    graph = course_graph()
    store.learning.create_version(graph)
    publish_sql(store, graph.id)
    set_source_fixture_state(store, rescinded_at=datetime.now(UTC))
    publication = store.learning.get_publication(graph.id)
    assert publication is not None and publication.state is CoursePublicationState.INVALIDATED
    with pytest.raises(LearningStateError, match="not serving from state invalidated"):
        store.learning.get_serving_version(graph.id, as_of=store.today, identity=store.identity)
    assert store.learning.get_version(graph.id) == graph
    reject_sql(
        store,
        "UPDATE learning_lessons SET title = 'Changed history' WHERE course_version_id = 'library-v1'",
        sqlstate="42501",
        message="immutable",
    )
    assert store.learning.get_version(graph.id) == graph
