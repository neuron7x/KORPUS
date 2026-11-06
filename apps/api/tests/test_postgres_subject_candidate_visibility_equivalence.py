"""Real PostgreSQL parity controls for the bounded subject-title candidate path (#27)."""

from __future__ import annotations

import json
from datetime import date

import pytest
from korpus.infrastructure.retrieval_queries import retrievable_projection
from korpus.infrastructure.retrieval_subject_query import subject_span_query
from korpus.infrastructure.schema import document_compartments, documents
from sqlalchemy import create_engine, insert, update

from apps.api.tests.conftest import reset_database
from apps.api.tests.test_postgres_candidate_visibility_equivalence import (
    ADMIN_URL,
    APP_URL,
    AS_OF,
    AUTHZ_URL,
    CORPORA,
    READER,
    _document,
    _repository,
    _version,
)

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not all((APP_URL, ADMIN_URL, AUTHZ_URL)),
        reason="real PostgreSQL app/admin/authz identities required",
    ),
]
TITLE = "PostgreSQL candidate admission control"


def _subject_candidates(identity=READER, *, limit: int = 1) -> tuple[set[str], list[str]]:
    repository = _repository()
    try:
        built = subject_span_query(identity, CORPORA, AS_OF, [TITLE], limit)
        assert built is not None
        statement, parameters = built
        with repository.engine.begin() as connection:
            repository._apply_postgres_identity(connection, identity)
            canonical = {
                str(row["span_id"])
                for row in connection.execute(
                    retrievable_projection(identity, CORPORA, AS_OF)
                ).mappings()
            }
            candidates = [
                str(row["span_id"]) for row in connection.execute(statement, parameters).mappings()
            ]
        assert set(candidates) <= canonical
        return canonical, candidates
    finally:
        repository.close()


def test_pg_subject_foreign_supersession_does_not_hide_visible_span() -> None:
    reset_database()
    assert ADMIN_URL
    admin = create_engine(ADMIN_URL, future=True)
    try:
        with admin.begin() as connection:
            victim = _document(connection)
            foreign = _document(connection)
            connection.execute(
                update(documents)
                .where(documents.c.id == foreign)
                .values(canonical_title="other subject")
            )
            victim_version, victim_span = _version(connection, victim, "quasar")
            _version(connection, foreign, "unrelated", supersedes=victim_version)
    finally:
        admin.dispose()
    canonical, candidates = _subject_candidates()
    assert victim_span in canonical
    assert candidates == [victim_span]


def test_pg_subject_future_supersession_does_not_hide_current_span() -> None:
    reset_database()
    assert ADMIN_URL
    admin = create_engine(ADMIN_URL, future=True)
    try:
        with admin.begin() as connection:
            document = _document(connection)
            version, current_span = _version(connection, document, "quasar")
            _version(
                connection,
                document,
                "unavailable future",
                supersedes=version,
                publication_date=date(2027, 1, 1),
                effective_from=None,
                is_current=False,
                revision="2",
            )
    finally:
        admin.dispose()
    canonical, candidates = _subject_candidates()
    assert current_span in canonical
    assert candidates == [current_span]


def test_pg_subject_compartment_filter_precedes_limit_with_positive_control() -> None:
    reset_database()
    assert ADMIN_URL
    admin = create_engine(ADMIN_URL, future=True)
    try:
        with admin.begin() as connection:
            span_docs = []
            for _ in range(3):
                document = _document(connection)
                _, span = _version(connection, document, "quasar")
                span_docs.append((span, document))
            span_docs.sort()
            for _, hidden_document in span_docs[:2]:
                connection.execute(
                    update(documents)
                    .where(documents.c.id == hidden_document)
                    .values(compartments_json=json.dumps(["alpha"]))
                )
                connection.execute(
                    insert(document_compartments).values(
                        document_id=hidden_document, compartment="alpha"
                    )
                )
    finally:
        admin.dispose()
    visible_span = span_docs[-1][0]
    canonical, candidates = _subject_candidates(limit=1)
    assert visible_span in canonical
    assert candidates == [visible_span]
    authorized = READER.model_copy(update={"compartments": frozenset({"alpha"})})
    allowed, selected = _subject_candidates(authorized, limit=1)
    assert {span for span, _document_id in span_docs} <= allowed
    assert selected == [span_docs[0][0]]
