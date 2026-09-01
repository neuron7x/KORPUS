from __future__ import annotations

from types import SimpleNamespace

from korpus.application.embedding_coverage import COMPLETE, STALE_VECTORS
from korpus.domain.models import AccessTier, Identity
from korpus.infrastructure.semantic import PgVectorSemanticIndex


class Result:
    def __init__(self, row: object) -> None:
        self.row = row

    def one(self) -> object:
        return self.row


class Connection:
    def __init__(self, row: object) -> None:
        self.row = row
        self.calls = 0
        self.parameters: dict[str, object] = {}

    def execute(self, statement: object, parameters: dict[str, object]) -> Result:
        assert "COUNT(*) FILTER" in str(statement)
        self.calls += 1
        self.parameters = parameters
        return Result(self.row)


class Context:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def __enter__(self) -> Connection:
        return self.connection

    def __exit__(self, *args: object) -> None:
        return None


class Engine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, row: object) -> None:
        self.connection = Connection(row)

    def begin(self) -> Context:
        return Context(self.connection)


def _identity() -> Identity:
    return Identity(
        subject="coverage-worker",
        roles=frozenset({"admin"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public", "training"}),
    )


def _index(row: object) -> PgVectorSemanticIndex:
    provider = SimpleNamespace(model_id="embed-v2", dimensions=8)
    return PgVectorSemanticIndex(Engine(row), provider)


def test_runtime_coverage_is_model_dimension_and_text_hash_bound(monkeypatch) -> None:
    # Прив'язку робить функція модуля, а не статичний метод класу: підклас із
    # межею RLS перевизначає МЕТОД, тож статичний виклик не міг би знати про брокера.
    monkeypatch.setattr(
        "korpus.infrastructure.repository.apply_session_claims", lambda *args: None
    )
    row = SimpleNamespace(
        spans_total=10,
        spans_embedded_active=10,
        spans_embedded_other_model=4,
        spans_stale_text=0,
    )
    index = _index(row)

    coverage = index.coverage(_identity(), frozenset({"training", "outside"}))

    assert coverage.status == COMPLETE
    assert coverage.coverage_ratio == 1.0
    assert index.engine.connection.parameters == {
        "model_id": "embed-v2",
        "dimensions": 8,
        "corpora": ["training"],
    }


def test_runtime_coverage_detects_stale_vectors(monkeypatch) -> None:
    # Прив'язку робить функція модуля, а не статичний метод класу: підклас із
    # межею RLS перевизначає МЕТОД, тож статичний виклик не міг би знати про брокера.
    monkeypatch.setattr(
        "korpus.infrastructure.repository.apply_session_claims", lambda *args: None
    )
    index = _index(
        SimpleNamespace(
            spans_total=10,
            spans_embedded_active=9,
            spans_embedded_other_model=0,
            spans_stale_text=1,
        )
    )

    assert index.coverage(_identity(), frozenset({"public"})).status == STALE_VECTORS


def test_empty_authorized_scope_never_queries_or_claims_complete() -> None:
    index = _index(SimpleNamespace())

    coverage = index.coverage(_identity(), frozenset({"outside"}))

    assert coverage.complete is False
    assert index.engine.connection.calls == 0
