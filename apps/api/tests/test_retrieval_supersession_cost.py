"""A timeout must not be reported as an empty corpus, so retrieval must not correlate.

Found by asking a real corpus real questions. The supersession test was a correlated
`NOT EXISTS`, and `ORDER BY bm25` forces every full-text match through it: on 116 229
spans a five-token question evaluated it 23 626 times and took 2.5 s against a 1200 ms
budget. `RetrievalDeadlineExceeded` then became an abstention, and what reached the
reader was "у чинному перевіреному корпусі недостатньо доказів" — the system stating the
corpus held nothing when it had simply not finished looking. Four of five ordinary
questions ("правила ведення вогню з кулемета", "робота з радіостанцією") answered that
way; after the rewrite they answer with citations from the Бойовий статут.

Asserted on the query *plan* rather than on a stopwatch or on the SQL text. A wall-clock
threshold measures the machine, and a regex over the statement passes the moment somebody
reformats it. `EXPLAIN QUERY PLAN` naming a correlated subquery is the defect itself:
that line is present exactly when the row-by-row evaluation is back.

The semantic half — that a superseded version stays out of the results — is not restated
here; it is what test_corpus_governance.py and test_currency_lower_bound.py already hold.
This file guards the shape of the answer to that question, not the answer.
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
    "CREATE TABLE document_versions (id TEXT PRIMARY KEY, document_id TEXT,"
    " review_state TEXT, effective_from TEXT, publication_date TEXT, effective_until TEXT,"
    " rescinded_at TEXT, supersedes_version_id TEXT)",
    "CREATE TABLE evidence_spans (id TEXT PRIMARY KEY, version_id TEXT, text TEXT)",
    "CREATE VIRTUAL TABLE evidence_fts USING fts5(span_id UNINDEXED, text)",
]


def test_the_supersession_test_is_not_evaluated_per_matching_span() -> None:
    plan = _plan(SCHEMA)

    correlated = [line for line in plan if "CORRELATED" in line.upper()]
    assert not correlated, (
        "the supersession test runs once per full-text match again; on a real corpus "
        f"that is 23 626 evaluations and a deadline breach reported as an empty corpus: {plan}"
    )


def test_the_plan_is_read_from_a_statement_that_actually_parses() -> None:
    """The negative control for the test above.

    A statement SQLite refuses to prepare produces no plan at all, and "no plan contains
    CORRELATED" is a sentence that is true of nothing. This asserts the plan exists and
    describes the query that was asked.
    """
    plan = _plan(SCHEMA)

    assert plan, "EXPLAIN QUERY PLAN returned nothing — the statement did not prepare"
    # The full-text table is aliased, so the plan names the alias; what identifies it is
    # that SQLite reached the fts5 virtual table at all.
    assert any("VIRTUAL TABLE" in line for line in plan), plan
    assert any("MATERIALIZE superseded" in line for line in plan), plan


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_both_dialects_gather_the_superseded_set_once(dialect: str) -> None:
    """Postgres has no EXPLAIN here, so the shared shape is asserted for both."""
    built = candidate_span_query(
        IDENTITY, frozenset({"public"}), date(2026, 8, 6), "кулемет", 256, dialect
    )
    assert built is not None
    sql = str(built[0])

    assert "WITH superseded AS" in sql, sql
    assert "NOT EXISTS" not in sql, (
        f"the correlated form is back in the {dialect} statement: {sql}"
    )
