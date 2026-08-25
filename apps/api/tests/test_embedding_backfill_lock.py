from __future__ import annotations

from types import SimpleNamespace

import pytest
from korpus.infrastructure.embedding_backfill_lock import _lock_key, exclusive_backfill_run


class Connection:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.statements: list[str] = []
        self.closed = False

    def execute(self, statement: object, parameters: dict[str, int]) -> object:
        self.statements.append(str(statement))
        return SimpleNamespace(scalar_one=lambda: self.acquired)

    def close(self) -> None:
        self.closed = True


def test_singleton_lock_is_stable_and_released() -> None:
    assert _lock_key("model-v1", 768) == _lock_key("model-v1", 768)
    assert _lock_key("model-v1", 768) != _lock_key("model-v2", 768)
    connection = Connection(acquired=True)
    engine = SimpleNamespace(connect=lambda: connection)

    with exclusive_backfill_run(engine, "model-v1", 768):
        assert connection.closed is False

    assert "pg_try_advisory_lock" in connection.statements[0]
    assert "pg_advisory_unlock" in connection.statements[1]
    assert connection.closed is True


def test_concurrent_backfill_is_refused_without_unlocking_foreign_lease() -> None:
    connection = Connection(acquired=False)
    engine = SimpleNamespace(connect=lambda: connection)

    with (
        pytest.raises(RuntimeError, match="already running"),
        exclusive_backfill_run(engine, "model-v1", 768),
    ):
        raise AssertionError("unreachable")

    assert len(connection.statements) == 1
    assert connection.closed is True
