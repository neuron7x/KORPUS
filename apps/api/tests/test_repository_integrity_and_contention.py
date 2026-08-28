"""The repository's fail-closed edges: integrity, retry classification, audit-chain races.

`healthcheck` exists because reachable is not intact — its own docstring says so. On
2026-08-28 the module measured 68.6% branch coverage and the untaken branches were the
ones that make that sentence true: the probe returning something other than 1, the
integrity check failing, the non-lock database error that must propagate rather than be
retried, and the guarded audit-head update finding the head already moved.

Each of these is a control whose absence is invisible in a green suite. A healthcheck
that cannot return False reports a corrupt database as ready; a retry loop that treats
every `OperationalError` as contention turns a schema fault into eight silent retries
and one misleading `ConcurrentWriteError`; an unguarded head update forks the hash chain.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from korpus.application.policy import PolicyEngine
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.repository import ConcurrentWriteError, SqlRepository
from sqlalchemy.exc import DatabaseError, OperationalError


@pytest.fixture
def repository(tmp_path: Path) -> SqlRepository:
    repository = SqlRepository(
        f"sqlite:///{tmp_path / 'integrity.db'}",
        "integrity-audit-key",
        PolicyEngine(),
        tmp_path / "anchor.json",
    )
    repository.initialize()
    return repository


@pytest.fixture
def reader() -> Identity:
    return Identity(
        subject="reader",
        roles=frozenset({"user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )


def test_a_sound_database_is_healthy(repository: SqlRepository) -> None:
    """The positive control: every refusal below is vacuous without it."""
    assert repository.healthcheck() is True


def test_a_probe_that_answers_anything_but_one_is_unhealthy(repository: SqlRepository) -> None:
    """A connection that answers `SELECT 1` wrongly is not a connection to trust."""
    with patch.object(SqlRepository, "_integrity_ok", return_value=True) as integrity, patch(
        "korpus.infrastructure.repository.select",
        side_effect=lambda *a, **k: __import__(
            "sqlalchemy"
        ).select(__import__("sqlalchemy").literal(2)),
    ):
        assert repository.healthcheck() is False
    integrity.assert_not_called()


def test_an_intact_connection_over_a_corrupt_file_is_unhealthy(repository: SqlRepository) -> None:
    """This is the case the docstring names: readable pages, wrong contents."""
    with patch.object(SqlRepository, "_integrity_ok", return_value=False):
        assert repository.healthcheck() is False


@pytest.mark.parametrize("failure", [OperationalError, DatabaseError])
def test_a_database_error_during_the_probe_reads_as_unhealthy(
    repository: SqlRepository, failure: type[Exception]
) -> None:
    """Fail closed: an unanswerable question is not a positive answer."""
    with patch.object(
        SqlRepository, "_integrity_ok", side_effect=failure("stmt", {}, Exception("down"))
    ):
        assert repository.healthcheck() is False


def test_quick_check_deciding_anything_but_ok_is_a_failure(repository: SqlRepository) -> None:
    """SQLite reports corruption as rows of text; only the exact single 'ok' row passes."""
    with repository.engine.connect() as connection:
        assert repository._integrity_ok(connection) is True

    class Rows:
        def __init__(self, values: list[str]) -> None:
            self._values = values

        def scalars(self) -> Rows:
            return self

        def all(self) -> list[str]:
            return self._values

    class FakeConnection:
        dialect = type("D", (), {"name": "sqlite"})()

        def __init__(self, values: list[str]) -> None:
            self._values = values

        def execute(self, *_: object, **__: object) -> Rows:
            return Rows(self._values)

    for damaged in (["*** in database main ***"], ["ok", "row 3 missing"], []):
        assert repository._integrity_ok(FakeConnection(damaged)) is False  # type: ignore[arg-type]


def test_an_unknown_dialect_is_not_claimed_to_be_corrupt(repository: SqlRepository) -> None:
    """No probe is not a failed probe; the engine-specific checks are the only evidence."""
    with (
        patch.object(type(repository.engine.dialect), "name", "duckdb"),
        repository.engine.connect() as connection,
    ):
        assert repository._integrity_ok(connection) is True


def test_a_database_error_that_is_not_contention_is_raised_immediately(
    repository: SqlRepository,
) -> None:
    """Retrying a syntax or schema fault eight times reports the wrong cause, slowly."""
    calls = 0

    def operation(_: object) -> tuple[None, tuple[int, str]]:
        nonlocal calls
        calls += 1
        raise OperationalError("stmt", {}, Exception("no such column: nonexistent"))

    with pytest.raises(OperationalError):
        repository._transaction_with_anchor(operation)  # type: ignore[arg-type]
    assert calls == 1, "a non-contention error must not consume the retry budget"


@pytest.mark.parametrize(
    "message",
    [
        "database is locked",
        "could not serialize access due to concurrent update",
        "could not serialize access due to read/write dependencies among transactions",
        "deadlock detected",
    ],
)
def test_contention_consumes_the_retry_budget_and_then_reports_it(
    repository: SqlRepository, message: str
) -> None:
    """Both dialects' contention wording is recognised, and exhaustion is named as such.

    The three PostgreSQL phrasings are the reason this test exists. The classifier used
    to look for the substring "serialization", which appears in none of them: on the
    deployment dialect a real serialization failure was re-raised on the first attempt
    rather than retried, and the retry budget the comment above it describes was only
    ever reachable from SQLite.
    """
    calls = 0

    def operation(_: object) -> tuple[None, tuple[int, str]]:
        nonlocal calls
        calls += 1
        raise OperationalError("stmt", {}, Exception(message))

    with pytest.raises(ConcurrentWriteError, match="retry budget exhausted"):
        repository._transaction_with_anchor(operation, retries=3)  # type: ignore[arg-type]
    assert calls == 3


def test_an_audit_head_that_moved_underneath_the_write_is_refused(
    repository: SqlRepository, reader: Identity
) -> None:
    """The guarded UPDATE is what keeps the hash chain a chain rather than a fork.

    Two appends that both read sequence n would both write n+1; the second one's
    `previous_hash` would name an event that is no longer the head, and verification
    would report a broken chain long after the write that caused it. The move is staged
    inside `sign`, which runs between the head read and the guarded update, so the race
    is deterministic rather than timing-dependent.
    """
    from korpus.infrastructure.schema import audit_heads
    from sqlalchemy import update

    class MovesTheHeadWhileSigning:
        """Stands in for the key ring so the move lands between read and update."""

        def __init__(self, inner: object, connection: object) -> None:
            self._inner = inner
            self._connection = connection

        def sign(self, canonical: bytes) -> tuple[str, str]:
            self._connection.execute(  # type: ignore[attr-defined]
                update(audit_heads)
                .where(audit_heads.c.singleton_id == 1)
                .values(head_hash="f" * 64)
            )
            return self._inner.sign(canonical)  # type: ignore[attr-defined]

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    with repository.engine.begin() as connection:
        original = repository.audit_keyring
        repository.audit_keyring = MovesTheHeadWhileSigning(original, connection)  # type: ignore[assignment]
        try:
            with pytest.raises(ConcurrentWriteError, match="head changed concurrently"):
                repository._append_audit_in_connection(
                    connection, reader, "test.race", "test", str(uuid4()), {}
                )
        finally:
            repository.audit_keyring = original


def test_a_reader_whose_corpora_do_not_intersect_reaches_no_query_at_all(
    repository: SqlRepository,
) -> None:
    """The intersection is taken before the query, and the short circuit is the point.

    Removing it changes no result — an empty `IN ()` returns nothing either way — so a
    test asserting `== []` cannot tell the two apart. What it does change is that every
    unauthorized read reaches the database and executes the projection over the whole
    corpus. At the scale this system is written for that is the cheapest denial of
    service in it, available to any authenticated reader, which is why the assertion
    here is that no connection is opened rather than that the list is empty.
    """
    from datetime import date

    outsider = Identity(
        subject="outsider",
        roles=frozenset({"user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"training"}),
    )

    with patch.object(
        repository.engine, "begin", side_effect=AssertionError("the database was reached")
    ):
        assert repository.list_retrievable_spans(
            outsider, frozenset({"public"}), date(2026, 1, 1)
        ) == []
        assert (
            repository.get_retrievable_spans_by_ids(
                outsider, frozenset({"public"}), date(2026, 1, 1), [uuid4()]
            )
            == []
        )


def test_an_empty_id_list_short_circuits_before_the_query(
    repository: SqlRepository, reader: Identity
) -> None:
    """`IN ()` is a syntax error in some dialects and a full scan in others."""
    from datetime import date

    with patch.object(
        repository.engine, "begin", side_effect=AssertionError("the database was reached")
    ):
        assert (
            repository.get_retrievable_spans_by_ids(
                reader, frozenset({"public"}), date(2026, 1, 1), []
            )
            == []
        )


def test_rescinding_a_version_that_is_not_approved_is_refused(
    repository: SqlRepository, reader: Identity
) -> None:
    """Withdrawal is an act on something in force; a draft was never in force."""
    with pytest.raises(LookupError, match="version not found"):
        repository.rescind_version(reader, uuid4(), note="withdrawn by issuer")


def _unmigrated(tmp_path: Path, name: str) -> SqlRepository:
    return SqlRepository(
        f"sqlite:///{tmp_path / name}",
        "schema-audit-key",
        PolicyEngine(),
        tmp_path / f"{name}.anchor.json",
    )


def test_an_empty_database_is_refused_when_the_caller_did_not_ask_to_create_it(
    tmp_path: Path,
) -> None:
    """`create_schema=False` is the production path: migrations own the schema.

    Falling back to `create_all` there would let a deployment start against a database
    alembic never touched — the tables would exist, the migration history would not, and
    the next migration would run against a shape nobody recorded.
    """
    repository = _unmigrated(tmp_path, "empty.db")
    with pytest.raises(RuntimeError, match="schema is not migrated"):
        repository.initialize(create_schema=False)


def test_a_schema_at_the_wrong_revision_is_refused(tmp_path: Path) -> None:
    """Table names matching is not the same as the schema matching.

    A revision behind can have every table and a missing column, and the failure would
    surface as a query error deep in a request rather than as a refusal to start.
    """
    from korpus.infrastructure.schema import SCHEMA_REVISION
    from sqlalchemy import text as sql_text

    repository = _unmigrated(tmp_path, "stale.db")
    repository.initialize()
    with repository.engine.begin() as connection:
        connection.execute(sql_text("CREATE TABLE IF NOT EXISTS alembic_version (version_num TEXT)"))
        connection.execute(sql_text("DELETE FROM alembic_version"))
        connection.execute(sql_text("INSERT INTO alembic_version VALUES ('0001_initial')"))

    assert repository.schema_revision() == "0001_initial"
    with pytest.raises(RuntimeError, match="schema revision mismatch"):
        repository.initialize(create_schema=False)

    with repository.engine.begin() as connection:
        connection.execute(sql_text("DELETE FROM alembic_version"))
        connection.execute(sql_text(f"INSERT INTO alembic_version VALUES ('{SCHEMA_REVISION}')"))
    repository.initialize(create_schema=False)


def test_a_migrated_schema_without_an_audit_head_is_refused(tmp_path: Path) -> None:
    """The head row is the anchor of the hash chain; seeding it here would fork it.

    On the creating path a fresh chain legitimately starts at zero. On the migrated path
    its absence means the migration that seeds it did not run, and writing a new genesis
    row would silently start a second chain beside whatever the deployment already had.
    """
    from korpus.infrastructure.schema import SCHEMA_REVISION, audit_heads
    from sqlalchemy import delete
    from sqlalchemy import text as sql_text

    repository = _unmigrated(tmp_path, "headless.db")
    repository.initialize()
    with repository.engine.begin() as connection:
        connection.execute(sql_text("CREATE TABLE IF NOT EXISTS alembic_version (version_num TEXT)"))
        connection.execute(sql_text("DELETE FROM alembic_version"))
        connection.execute(sql_text(f"INSERT INTO alembic_version VALUES ('{SCHEMA_REVISION}')"))
        connection.execute(delete(audit_heads))

    with pytest.raises(RuntimeError, match="no audit head"):
        repository.initialize(create_schema=False)
