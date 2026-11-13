from __future__ import annotations

from pathlib import Path
from types import CodeType, FunctionType

import pytest
from alembic import command
from korpus.infrastructure.migration_admission import MigrationAdmissionError
from korpus.infrastructure.migration_readonly import inspection_transaction
from sqlalchemy import Connection, create_engine
from sqlalchemy.exc import OperationalError


def _inspection_callback() -> FunctionType:
    code = next(
        value
        for value in command.current.__code__.co_consts
        if isinstance(value, CodeType) and value.co_name == "display_version"
    )
    cell = (lambda value: lambda: value)(None).__closure__
    assert cell is not None
    return FunctionType(code, {}, closure=cell * len(code.co_freevars))


def test_inspection_transaction_cannot_write_even_with_authentic_callback(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'inspection.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE sentinel(value TEXT)")
        connection.exec_driver_sql("INSERT INTO sentinel VALUES ('preserve')")
    with engine.connect() as connection:
        with (
            pytest.raises(OperationalError, match="readonly"),
            inspection_transaction(connection, _inspection_callback()),
        ):
            connection.exec_driver_sql("DELETE FROM sentinel")
        assert connection.exec_driver_sql("SELECT value FROM sentinel").all() == [("preserve",)]
    engine.dispose()


def test_unknown_callback_cannot_select_the_inspection_lane(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'unknown.db'}")

    def counterfeit(connection: Connection) -> None:
        connection.exec_driver_sql("CREATE TABLE illicit(value TEXT)")

    with engine.connect() as connection:
        with (
            pytest.raises(MigrationAdmissionError, match="DENIED_OPERATION_UNPROVEN"),
            inspection_transaction(connection, counterfeit),
        ):
            counterfeit(connection)
        assert connection.exec_driver_sql("SELECT name FROM sqlite_master").all() == []
    engine.dispose()
