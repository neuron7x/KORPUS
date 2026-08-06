"""COD-001: the seams cut out of `SqlRepository`, held open.

Three moves have happened: the audit read side (audit_reader.py), the row mappers
(row_mapping.py), and on 2026-08-05 the physical schema (schema.py) and the retrieval
projection (retrieval_queries.py). 1855 lines became 1047.

An extraction that nothing asserts is an extraction the next edit undoes, so these tests
pin the property the split exists for: the query builders construct statements and do
not reach a database, and the schema module declares tables and does not import the
repository that reads them. Both are checked structurally, because "no database access"
is not something a passing query test can demonstrate — a builder that opened its own
connection would still return the right rows.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure import retrieval_queries, row_mapping, schema
from korpus.infrastructure.repository import SqlRepository

SOURCE = Path(retrieval_queries.__file__)
SCHEMA_SOURCE = Path(schema.__file__)


def _names_called(tree: ast.AST) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_the_query_builders_never_open_a_connection() -> None:
    """The line the split draws.

    Construction is pure and testable without a database; executing it needs the RLS
    session context and the retry envelope, which stay in the repository. A builder that
    quietly opened its own connection would bypass `_apply_postgres_identity` — the
    call that sets the PostgreSQL row-level security context — and nothing in a
    behavioural test on SQLite would notice, because SQLite has no RLS to bypass.
    """
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    called = _names_called(tree)

    for forbidden in ("connect", "begin", "execute", "create_engine"):
        assert forbidden not in called, (
            f"retrieval_queries.{forbidden}() reaches a database; building a statement "
            "and running it are different responsibilities and only one of them needs "
            "the RLS session context"
        )


def test_the_schema_module_does_not_import_what_reads_it() -> None:
    """Otherwise the cycle comes back and the split is nominal."""
    tree = ast.parse(SCHEMA_SOURCE.read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not any(
        module.startswith("korpus.infrastructure.repository")
        or module.startswith("korpus.infrastructure.retrieval_queries")
        for module in imported
    ), f"schema.py imports its own readers: {sorted(imported)}"


def test_the_schema_still_answers_to_its_old_name() -> None:
    """Every migration, test and mutant names these on `repository`."""
    from korpus.infrastructure import repository

    for name in (
        "documents",
        "versions",
        "spans",
        "document_compartments",
        "span_embeddings",
        "audits",
        "audit_heads",
        "audit_anchor_outbox",
        "metadata",
        "SCHEMA_REVISION",
    ):
        assert getattr(repository, name) is getattr(schema, name), (
            f"repository.{name} is no longer the schema module's object"
        )


def test_the_repository_delegates_rather_than_keeping_a_second_copy() -> None:
    assert SqlRepository._retrievable_projection is retrieval_queries.retrievable_projection
    assert SqlRepository._materialize_current is retrieval_queries.materialize_current
    assert SqlRepository._compartment_predicate is retrieval_queries.compartment_predicate
    assert SqlRepository._document is row_mapping.document


def _identity(clearance: AccessTier, compartments: frozenset[str] = frozenset()) -> Identity:
    return Identity(
        subject="reader",
        roles=frozenset({"user"}),
        clearance=clearance,
        corpora=frozenset({"public"}),
        compartments=compartments,
    )


def test_the_projection_carries_every_access_predicate_it_is_supposed_to() -> None:
    """Compiled and read, so a dropped `.where` is visible without a corpus behind it.

    These five clauses are the whole access decision at the retrieval layer. A
    behavioural test proves they work together on the rows that exist; this proves none
    of them silently stopped being emitted.
    """
    statement = retrieval_queries.retrievable_projection(
        _identity(AccessTier.REVIEWED), frozenset({"public"}), date(2026, 8, 5)
    )
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))

    assert "review_state = 'approved'" in sql
    assert "corpus_id IN ('public')" in sql
    assert "access_tier <= 2" in sql
    assert "classification IN" in sql
    assert "NOT (EXISTS" in sql
    assert "document_compartments" in sql


def test_a_reader_with_no_compartments_still_gets_the_compartment_predicate() -> None:
    """The empty case is the dangerous one: no compartments must mean no compartmented
    material, not an unfiltered query."""
    without = str(
        retrieval_queries.compartment_predicate(_identity(AccessTier.PUBLIC)).compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    withheld = str(
        retrieval_queries.compartment_predicate(
            _identity(AccessTier.PUBLIC, frozenset({"ops-north"}))
        ).compile(compile_kwargs={"literal_binds": True})
    )

    # Without compartments the predicate is "no compartment row may exist", with no
    # exception list. With one, the exception list names it. The failure to guard
    # against is the empty case compiling to nothing at all.
    assert without.startswith("NOT (EXISTS")
    assert "document_compartments" in without
    assert "NOT IN" not in without
    assert "NOT IN ('ops-north')" in withheld


def test_a_query_with_no_usable_term_returns_no_statement() -> None:
    """None, not an empty statement: the caller must not open a transaction for it."""
    assert (
        retrieval_queries.candidate_span_query(
            _identity(AccessTier.PUBLIC), frozenset({"public"}), date(2026, 8, 5), "  ", 10,
            "sqlite",
        )
        is None
    )


def test_an_unsupported_dialect_refuses_rather_than_returning_a_broken_statement() -> None:
    with pytest.raises(RuntimeError, match="unsupported search dialect"):
        retrieval_queries.candidate_span_query(
            _identity(AccessTier.PUBLIC), frozenset({"public"}), date(2026, 8, 5),
            "наказ", 10, "mysql",
        )


def test_the_candidate_query_binds_the_readers_clearance_rather_than_a_constant() -> None:
    prepared = retrieval_queries.candidate_span_query(
        _identity(AccessTier.REVIEWED), frozenset({"public"}), date(2026, 8, 5),
        "наказ", 25, "sqlite",
    )
    assert prepared is not None
    _, parameters = prepared

    assert parameters["clearance"] == 2
    assert parameters["as_of"] == "2026-08-05"
    assert parameters["limit"] == 25
    assert parameters["corpus_0"] == "public"
