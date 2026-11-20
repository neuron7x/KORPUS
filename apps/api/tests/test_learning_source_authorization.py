"""SQLite policy controls; these do not claim to execute PostgreSQL RLS."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from korpus.application.policy import AuthorizationError
from korpus.domain.learning import Course, CoursePublicationState
from korpus.domain.models import Identity
from korpus.infrastructure.learning_repository import LearningStateError, SqlLearningRepository
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.schema import documents
from pydantic import ValidationError
from sqlalchemy import update

from apps.api.tests.learning_postgres_support import (
    OTHER_SOURCE,
    SOURCE,
    _seed_source,
    course_graph,
)

AUTHOR = Identity(
    subject="library-author",
    roles=frozenset({"instructor"}),
    corpora=frozenset({"public", "library-other"}),
)
READER = Identity(subject="library-reader", roles=frozenset({"user"}))


@pytest.fixture
def learning(tmp_path: Path) -> Iterator[SqlLearningRepository]:
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'learning-scope.db'}",
        "learning-policy-key",
        audit_anchor_path=tmp_path / "anchor.json",
    )
    repository.initialize()
    try:
        for source in (SOURCE, OTHER_SOURCE):
            _seed_source(repository.engine, source, date.today())
        with repository.engine.begin() as connection:
            connection.execute(
                update(documents)
                .where(documents.c.id == str(OTHER_SOURCE[0]))
                .values(corpus_id="library-other")
            )
        learning = SqlLearningRepository(repository.engine)
        learning.create_course(Course(id="library", specialty_id="public", title="Library basics"))
        learning.create_version(course_graph())
        yield learning
    finally:
        repository.close()


def test_learning_authorized_identity_preserves_exact_source_graph(
    learning: SqlLearningRepository,
) -> None:
    graph = course_graph()
    assert learning.validate_version(graph.id, identity=AUTHOR).publishable
    assert (
        learning.publish_version(graph.id, reviewed_by="course-reviewer", identity=AUTHOR).state
        is CoursePublicationState.PUBLISHED
    )
    assert learning.get_serving_version(graph.id, identity=AUTHOR) == graph


@pytest.mark.parametrize("operation", ["validate", "publish"])
def test_learning_source_substitution_outside_identity_scope_is_denied(
    learning: SqlLearningRepository,
    operation: str,
) -> None:
    graph = course_graph()
    before = learning.get_publication(graph.id)
    with pytest.raises(AuthorizationError, match="outside the authorized scope"):
        if operation == "validate":
            learning.validate_version(graph.id, identity=READER)
        else:
            learning.publish_version(graph.id, reviewed_by="course-reviewer", identity=READER)
    assert learning.get_publication(graph.id) == before
    assert learning.get_version(graph.id) == graph


def test_learning_hidden_source_does_not_invalidate_publication(
    learning: SqlLearningRepository,
) -> None:
    graph = course_graph()
    learning.publish_version(graph.id, reviewed_by="course-reviewer", identity=AUTHOR)
    before = learning.get_publication(graph.id)
    with pytest.raises(AuthorizationError, match="outside the authorized scope"):
        learning.get_serving_version(graph.id, identity=READER)
    assert learning.get_publication(graph.id) == before
    assert learning.get_serving_version(graph.id, identity=AUTHOR) == graph


def test_learning_authorized_reader_detects_expired_canonical_source(
    learning: SqlLearningRepository,
) -> None:
    graph = course_graph()
    learning.publish_version(graph.id, reviewed_by="course-reviewer", identity=AUTHOR)
    with pytest.raises(LearningStateError, match="no longer source-valid"):
        learning.get_serving_version(
            graph.id, as_of=date.today() + timedelta(days=60), identity=AUTHOR
        )
    publication = learning.get_publication(graph.id)
    assert publication is not None and publication.state is CoursePublicationState.INVALIDATED
    assert learning.get_version(graph.id) == graph


@pytest.mark.parametrize("field", ["corpora", "compartments"])
@pytest.mark.parametrize("value", ["*", "library-other/*", "library-other,public"])
def test_learning_source_identity_uses_existing_strict_scope_vocabulary(
    field: str, value: str
) -> None:
    with pytest.raises(ValidationError, match="invalid corpus or compartment identifier"):
        Identity(subject="library-reader", **{field: frozenset({value})})
