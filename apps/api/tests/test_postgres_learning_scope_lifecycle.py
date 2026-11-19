"""Additional #100 hypotheses, separate from the first hosted persistence baseline."""

from __future__ import annotations

import pytest
from korpus.application.policy import AuthorizationError
from korpus.domain.learning import Course, CoursePublicationState
from korpus.domain.models import Identity
from korpus.infrastructure.learning_repository import SqlLearningRepository
from korpus.infrastructure.schema import documents
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError

from apps.api.tests.learning_postgres_support import (
    OTHER_SOURCE,
    LearningPostgres,
    course_graph,
    publish_sql,
    reject_sql,
)
from apps.api.tests.learning_postgres_support import (
    learning_postgres as learning_postgres,
)

pytestmark = pytest.mark.postgres

READER = Identity(subject="public-library-reader", roles=frozenset({"user"}))


def _separate_source_scope(store: LearningPostgres) -> None:
    """Prepare two neutral corpora; no course category is treated as an access grant."""
    with store.fixture_owner.begin() as connection:
        result = connection.execute(
            update(documents)
            .where(documents.c.id == str(OTHER_SOURCE[0]))
            .values(corpus_id="library-other")
        )
        assert result.rowcount == 1


@pytest.mark.parametrize("missing", ["identity", "binder"])
def test_postgres_learning_requires_explicit_trusted_context(
    learning_postgres: LearningPostgres, missing: str
) -> None:
    store = learning_postgres
    graph = course_graph()
    store.learning.create_version(graph)
    repository = SqlLearningRepository(store.app) if missing == "binder" else store.learning
    identity = store.identity if missing == "binder" else None
    before = store.learning.get_publication(graph.id)
    with pytest.raises(AuthorizationError, match="trusted learning source identity and binder"):
        repository.publish_version(graph.id, reviewed_by="course-reviewer", identity=identity)
    assert store.learning.get_publication(graph.id) == before


def test_postgres_learning_repository_rejects_cross_corpus_source_substitution(
    learning_postgres: LearningPostgres,
) -> None:
    store = learning_postgres
    _separate_source_scope(store)
    graph = course_graph()
    store.learning.create_version(graph)
    with pytest.raises(AuthorizationError, match="outside the authorized scope"):
        store.learning.publish_version(graph.id, reviewed_by="course-reviewer", identity=READER)
    publication = store.learning.get_publication(graph.id)
    assert publication is not None and publication.state is CoursePublicationState.DRAFT
    assert (
        store.learning.publish_version(
            graph.id, reviewed_by="course-reviewer", identity=store.identity
        ).state
        is CoursePublicationState.PUBLISHED
    )


def test_postgres_learning_hidden_source_cannot_invalidate_an_authorized_publication(
    learning_postgres: LearningPostgres,
) -> None:
    store = learning_postgres
    _separate_source_scope(store)
    graph = course_graph()
    store.learning.create_version(graph)
    store.learning.publish_version(graph.id, reviewed_by="course-reviewer", identity=store.identity)
    before = store.learning.get_publication(graph.id)
    with pytest.raises(AuthorizationError, match="outside the authorized scope"):
        store.learning.get_serving_version(graph.id, identity=READER)
    assert store.learning.get_publication(graph.id) == before
    assert store.learning.get_serving_version(graph.id, identity=store.identity) == graph


def test_postgres_learning_sql_publication_rejects_cross_corpus_source_substitution(
    learning_postgres: LearningPostgres,
) -> None:
    """New SQL scope hypothesis: the initial hosted baseline did not exercise this case."""
    store = learning_postgres
    _separate_source_scope(store)
    graph = course_graph()
    store.learning.create_version(graph)
    with pytest.raises(DBAPIError, match="authorized scope") as failure:
        publish_sql(store, graph.id, identity=READER)
    assert getattr(failure.value.orig, "sqlstate", None) == "42501"
    publication = store.learning.get_publication(graph.id)
    assert publication is not None and publication.state is CoursePublicationState.DRAFT
    publish_sql(store, graph.id)


@pytest.mark.parametrize("state", ["published", "invalidated", "retired"])
def test_postgres_learning_lifecycle_cannot_return_to_draft(
    learning_postgres: LearningPostgres, state: str
) -> None:
    store = learning_postgres
    graph = course_graph()
    store.learning.create_version(graph)
    publish_sql(store, graph.id)
    if state != "published":
        with store.app.begin() as connection:
            connection.execute(
                text("UPDATE learning_publications SET state = :state"), {"state": state}
            )
    before = store.learning.get_publication(graph.id)
    reject_sql(
        store,
        "UPDATE learning_publications SET state = 'draft' WHERE course_version_id = 'library-v1'",
        sqlstate="23514",
        message="transition|resurrected",
    )
    assert store.learning.get_publication(graph.id) == before
    assert store.learning.get_version(graph.id) == graph


@pytest.mark.parametrize("state", ["draft", "published", "invalidated", "retired"])
def test_postgres_learning_publication_identity_cannot_be_reparented(
    learning_postgres: LearningPostgres, state: str
) -> None:
    store = learning_postgres
    first, second = course_graph(), course_graph(revision="2")
    for graph in (first, second):
        store.learning.create_version(graph)
    if state != "draft":
        publish_sql(store, first.id)
    with store.app.begin() as connection:
        if state in {"invalidated", "retired"}:
            connection.execute(
                text(
                    "UPDATE learning_publications SET state = :state WHERE course_version_id = :id"
                ),
                {"state": state, "id": first.id},
            )
        assert (
            connection.execute(
                text("DELETE FROM learning_publications WHERE course_version_id = 'library-v2'")
            ).rowcount
            == 1
        )
    before = store.learning.get_publication(first.id)
    reject_sql(
        store,
        "UPDATE learning_publications SET course_version_id = 'library-v2' "
        "WHERE course_version_id = 'library-v1'",
        sqlstate="42501",
        message="publication identity is immutable",
    )
    assert store.learning.get_publication(first.id) == before
    assert store.learning.get_publication(second.id) is None
    assert store.learning.get_version(first.id) == first


def test_postgres_learning_draft_content_and_identity_remain_mutable(
    learning_postgres: LearningPostgres,
) -> None:
    store = learning_postgres
    graph = course_graph()
    store.learning.create_version(graph)
    with store.app.begin() as connection:
        assert (
            connection.execute(
                text("UPDATE learning_courses SET title = 'Revised library course'")
            ).rowcount
            == 1
        )
        assert (
            connection.execute(
                text("UPDATE learning_lessons SET title = 'Revised catalog' WHERE id = 'catalog'")
            ).rowcount
            == 1
        )
        assert connection.execute(text("DELETE FROM learning_block_sources")).rowcount == 2
    course = store.learning.get_course(graph.course_id)
    assert course == Course(id="library", specialty_id="public", title="Revised library course")
    updated = store.learning.get_version(graph.id)
    assert updated is not None and updated.modules[0].lessons[0].title == "Revised catalog"
    assert store.learning.delete_draft_version(graph.id)
    assert store.learning.get_version(graph.id) is None
    assert store.learning.get_publication(graph.id) is None
    with store.app.begin() as connection:
        assert connection.execute(text("DELETE FROM learning_courses")).rowcount == 1


def test_postgres_learning_block_binding_cannot_reference_another_course_graph(
    learning_postgres: LearningPostgres,
) -> None:
    store = learning_postgres
    first, other = (
        course_graph(),
        course_graph(revision="2").model_copy(update={"course_id": "other-library"}),
    )
    store.learning.create_course(
        Course(id="other-library", specialty_id="public", title="Other library course")
    )
    store.learning.create_version(first)
    store.learning.create_version(other)
    with store.app.begin() as connection:
        connection.execute(
            text("DELETE FROM learning_block_sources WHERE course_version_id = 'library-v2'")
        )
        connection.execute(
            text("DELETE FROM learning_source_binding_spans WHERE course_version_id = 'library-v2'")
        )
        assert (
            connection.execute(
                text(
                    "UPDATE learning_source_bindings SET id = 'foreign-source' "
                    "WHERE course_version_id = 'library-v2' AND id = 'source'"
                )
            ).rowcount
            == 2
        )
    reject_sql(
        store,
        "UPDATE learning_block_sources SET binding_id = 'foreign-source' "
        "WHERE course_version_id = 'library-v1'",
        sqlstate="23503",
        message="foreign key constraint",
    )
    assert store.learning.get_version(first.id) == first
