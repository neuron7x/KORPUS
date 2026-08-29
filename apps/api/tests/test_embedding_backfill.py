from __future__ import annotations

from types import SimpleNamespace

import pytest
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.embedding_backfill import PgVectorEmbeddingBackfill


class Result:
    def __init__(self, rows=(), rowcount: int = 0) -> None:
        self.rows = list(rows)
        self.rowcount = rowcount

    def all(self):
        return self.rows


class Connection:
    def __init__(self, rows, write_counts=()) -> None:
        self.rows = rows
        self.write_counts = iter(write_counts)
        self.statements: list[str] = []

    def execute(self, statement, parameters=None):
        del parameters
        rendered = str(statement)
        self.statements.append(rendered)
        if rendered.lstrip().startswith("SELECT s.id"):
            return Result(self.rows)
        return Result(rowcount=next(self.write_counts))


class Context:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *args):
        return None


class Engine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, connection) -> None:
        self.connection = connection

    def begin(self):
        return Context(self.connection)


class Provider:
    model_id = "embed-v2"
    dimensions = 8

    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    def embed_many(self, texts):
        self.inputs.append(texts)
        return [[0.125] * 8 for _ in texts]


class Governance:
    def __init__(self) -> None:
        self.calls = []

    def require_external_embedding(self, corpora):
        self.calls.append(corpora)


@pytest.fixture
def identity() -> Identity:
    return Identity(
        subject="backfill",
        roles=frozenset({"curator"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
    )


def test_database_state_is_resume_checkpoint_and_stale_writes_are_discarded(
    monkeypatch, identity
) -> None:
    from korpus.infrastructure.repository import SqlRepository

    monkeypatch.setattr(SqlRepository, "_apply_postgres_identity", lambda *args: None)
    rows = [
        SimpleNamespace(id="a", text="alpha", text_hash="1" * 64, corpus_id="public"),
        SimpleNamespace(id="b", text="beta", text_hash="2" * 64, corpus_id="public"),
    ]
    connection = Connection(rows, write_counts=(1, 0))
    provider, governance = Provider(), Governance()
    worker = PgVectorEmbeddingBackfill(
        Engine(connection), provider, batch_size=2, corpus_governance=governance
    )

    result = worker.run_batch(identity)

    assert (result.selected, result.written, result.stale_during_write) == (2, 1, 1)
    assert result.complete is False
    assert provider.inputs == [["alpha", "beta"]]
    assert governance.calls == [frozenset({"public"})]
    assert any(
        "s.text_hash = CAST(:text_hash AS varchar(64))" in sql for sql in connection.statements
    )


def test_empty_selection_is_complete_without_provider_call(monkeypatch, identity) -> None:
    from korpus.infrastructure.repository import SqlRepository

    monkeypatch.setattr(SqlRepository, "_apply_postgres_identity", lambda *args: None)
    provider = Provider()
    result = PgVectorEmbeddingBackfill(Engine(Connection([])), provider).run_batch(identity)

    assert result.complete is True
    assert provider.inputs == []


def test_backfill_bounds_and_postgres_requirement() -> None:
    connection, provider = Connection([]), Provider()
    sqlite = Engine(connection)
    sqlite.dialect = SimpleNamespace(name="sqlite")
    with pytest.raises(ValueError, match="requires PostgreSQL"):
        PgVectorEmbeddingBackfill(sqlite, provider)
    with pytest.raises(ValueError, match="must not exceed"):
        PgVectorEmbeddingBackfill(Engine(connection), provider, batch_size=65)
