"""Candidate ranking may spend its bounded budget only on canonically visible rows."""

from __future__ import annotations

from datetime import date

from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.retrieval_queries import candidate_span_query
from sqlalchemy import create_engine, text

READER = Identity(
    subject="candidate-reader",
    roles=frozenset({"user"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public"}),
)
AS_OF = date(2026, 8, 14)

_SCHEMA = (
    "CREATE TABLE documents (id TEXT PRIMARY KEY, corpus_id TEXT, access_tier INT, "
    "classification TEXT)",
    "CREATE TABLE document_compartments (document_id TEXT, compartment TEXT, "
    "PRIMARY KEY (document_id, compartment))",
    "CREATE TABLE document_versions (id TEXT PRIMARY KEY, document_id TEXT, "
    "review_state TEXT, effective_from TEXT, publication_date TEXT, effective_until TEXT, "
    "rescinded_at TEXT, supersedes_version_id TEXT)",
    "CREATE TABLE evidence_spans (id TEXT PRIMARY KEY, version_id TEXT, text TEXT)",
    "CREATE VIRTUAL TABLE evidence_fts USING fts5(span_id UNINDEXED, text)",
)


def _engine():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        for ddl in _SCHEMA:
            connection.execute(text(ddl))
    return engine


def _document(connection, document_id: str, *, compartments: tuple[str, ...] = ()) -> None:
    connection.execute(
        text(
            "INSERT INTO documents(id, corpus_id, access_tier, classification) "
            "VALUES (:id, 'public', 0, 'public')"
        ),
        {"id": document_id},
    )
    for compartment in compartments:
        connection.execute(
            text(
                "INSERT INTO document_compartments(document_id, compartment) "
                "VALUES (:id, :compartment)"
            ),
            {"id": document_id, "compartment": compartment},
        )


def _version(
    connection,
    version_id: str,
    document_id: str,
    *,
    supersedes: str | None = None,
) -> None:
    connection.execute(
        text(
            "INSERT INTO document_versions("
            "id, document_id, review_state, effective_from, publication_date, "
            "effective_until, rescinded_at, supersedes_version_id) "
            "VALUES (:id, :document_id, 'approved', '2026-01-01', '2026-01-01', "
            "NULL, NULL, :supersedes)"
        ),
        {"id": version_id, "document_id": document_id, "supersedes": supersedes},
    )


def _span(connection, span_id: str, version_id: str, body: str) -> None:
    connection.execute(
        text("INSERT INTO evidence_spans(id, version_id, text) VALUES (:id, :version, :body)"),
        {"id": span_id, "version": version_id, "body": body},
    )
    connection.execute(
        text("INSERT INTO evidence_fts(span_id, text) VALUES (:id, :body)"),
        {"id": span_id, "body": body},
    )


def _candidates(
    connection,
    query: str,
    *,
    identity: Identity = READER,
    limit: int = 8,
) -> list[str]:
    built = candidate_span_query(identity, frozenset({"public"}), AS_OF, query, limit, "sqlite")
    assert built is not None
    statement, parameters = built
    return [str(row.span_id) for row in connection.execute(statement, parameters)]


def test_cross_document_supersession_cannot_remove_a_candidate() -> None:
    engine = _engine()
    try:
        with engine.begin() as connection:
            _document(connection, "victim-doc")
            _document(connection, "foreign-doc")
            _version(connection, "victim-version", "victim-doc")
            _version(
                connection,
                "foreign-version",
                "foreign-doc",
                supersedes="victim-version",
            )
            _span(connection, "victim-span", "victim-version", "унікальний маркер журналу")

            assert _candidates(connection, "унікальний маркер") == ["victim-span"]
    finally:
        engine.dispose()


def test_invisible_compartment_rows_cannot_consume_candidate_budget() -> None:
    engine = _engine()
    try:
        with engine.begin() as connection:
            _document(connection, "hidden-doc", compartments=("alpha",))
            _document(connection, "visible-doc")
            _version(connection, "hidden-version", "hidden-doc")
            _version(connection, "visible-version", "visible-doc")
            _span(connection, "hidden-span-a", "hidden-version", "маскування позиції")
            _span(connection, "visible-span-z", "visible-version", "маскування позиції")

            assert _candidates(connection, "маскування", limit=1) == ["visible-span-z"]
    finally:
        engine.dispose()


def test_assigned_compartment_is_admitted_but_partial_assignment_is_not() -> None:
    engine = _engine()
    try:
        with engine.begin() as connection:
            _document(connection, "alpha-doc", compartments=("alpha",))
            _document(connection, "alpha-bravo-doc", compartments=("alpha", "bravo"))
            _version(connection, "alpha-version", "alpha-doc")
            _version(connection, "alpha-bravo-version", "alpha-bravo-doc")
            _span(connection, "alpha-span", "alpha-version", "контроль сектору")
            _span(connection, "alpha-bravo-span", "alpha-bravo-version", "контроль сектору")
            alpha_reader = READER.model_copy(update={"compartments": frozenset({"alpha"})})

            assert _candidates(connection, "контроль", identity=alpha_reader) == ["alpha-span"]
    finally:
        engine.dispose()
