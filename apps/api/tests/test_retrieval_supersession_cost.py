"""A timeout must not be reported as an empty corpus, so supersession cannot correlate.

The original per-match supersession predicate regressed real retrieval past its budget.
The candidate query therefore materializes the active superseder set once and anti-joins
against it. Visibility predicates may still be correlated to the current document; this
suite distinguishes that safe bounded lookup from a correlated document_versions scan.
"""

from __future__ import annotations

from datetime import date

import pytest
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.retrieval_queries import candidate_span_query
from sqlalchemy import create_engine, text

IDENTITY = Identity(
    subject="reader",
    roles=frozenset({"user"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public"}),
)


def _statement() -> tuple[str, dict[str, object]]:
    built = candidate_span_query(
        IDENTITY,
        frozenset({"public"}),
        date(2026, 8, 6),
        "правила ведення вогню з кулемета",
        256,
        "sqlite",
    )
    assert built is not None, "a query with usable terms produced no statement"
    statement, parameters = built
    return str(statement), dict(parameters)


def _plan(schema: list[str]) -> list[str]:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            for ddl in schema:
                connection.execute(text(ddl))
            sql, parameters = _statement()
            rows = connection.execute(text(f"EXPLAIN QUERY PLAN {sql}"), parameters).fetchall()
        return [str(row[-1]) for row in rows]
    finally:
        engine.dispose()


SCHEMA = [
    "CREATE TABLE documents (id TEXT PRIMARY KEY, corpus_id TEXT, access_tier INT,"
    " classification TEXT)",
    "CREATE TABLE document_compartments (document_id TEXT, compartment TEXT,"
    " PRIMARY KEY (document_id, compartment))",
    "CREATE TABLE document_versions (id TEXT PRIMARY KEY, document_id TEXT,"
    " review_state TEXT, effective_from TEXT, publication_date TEXT, effective_until TEXT,"
    " rescinded_at TEXT, supersedes_version_id TEXT)",
    "CREATE TABLE evidence_spans (id TEXT PRIMARY KEY, version_id TEXT, text TEXT)",
    "CREATE VIRTUAL TABLE evidence_fts USING fts5(span_id UNINDEXED, text)",
]


def test_the_supersession_test_is_not_evaluated_per_matching_span() -> None:
    plan = _plan(SCHEMA)

    correlated_version_scans = [
        line
        for line in plan
        if "CORRELATED" in line.upper() and "DOCUMENT_VERSIONS" in line.upper()
    ]
    assert not correlated_version_scans, (
        "active superseders are being rescanned for each full-text candidate: "
        f"{correlated_version_scans}"
    )


def test_the_plan_is_read_from_a_statement_that_actually_parses() -> None:
    plan = _plan(SCHEMA)

    assert plan, "EXPLAIN QUERY PLAN returned nothing — the statement did not prepare"
    assert any("VIRTUAL TABLE" in line for line in plan), plan
    assert any("MATERIALIZE superseded" in line for line in plan), plan


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_both_dialects_gather_same_document_superseders_once(dialect: str) -> None:
    built = candidate_span_query(
        IDENTITY, frozenset({"public"}), date(2026, 8, 6), "кулемет", 256, dialect
    )
    assert built is not None
    sql = str(built[0])

    assert "WITH superseded AS" in sql, sql
    assert "sv.supersedes_version_id AS id, sv.document_id AS document_id" in sql, sql
    assert "(v.id, v.document_id) NOT IN (SELECT id, document_id FROM superseded)" in sql, sql


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_both_dialects_filter_compartments_before_candidate_limit(dialect: str) -> None:
    identity = IDENTITY.model_copy(update={"compartments": frozenset({"alpha"})})
    built = candidate_span_query(
        identity, frozenset({"public"}), date(2026, 8, 6), "кулемет", 1, dialect
    )
    assert built is not None
    sql, parameters = built

    assert "document_compartments dc" in str(sql)
    assert "dc.document_id = d.id" in str(sql)
    assert "dc.compartment NOT IN (:compartment_0)" in str(sql)
    assert parameters["compartment_0"] == "alpha"
