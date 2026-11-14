"""Preserve Alembic inspection commands without giving them a DDL bypass."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import CodeType, FunctionType

from alembic import command
from sqlalchemy import Connection

from korpus.infrastructure.migration_admission import MigrationAdmissionError

_INSPECTION_CALLBACKS = frozenset(
    constant
    for operation in (command.current, command.check)
    for constant in operation.__code__.co_consts
    if isinstance(constant, CodeType)
)
_MIGRATION_CALLBACKS = frozenset(
    constant
    for operation in (command.upgrade, command.downgrade)
    for constant in operation.__code__.co_consts
    if isinstance(constant, CodeType)
)


def assert_migration_callback(callback: object) -> None:
    if not isinstance(callback, FunctionType) or callback.__code__ not in _MIGRATION_CALLBACKS:
        raise MigrationAdmissionError("DENIED_OPERATION_UNPROVEN")


@contextmanager
def inspection_transaction(connection: Connection, callback: object) -> Iterator[None]:
    """Only actual installed Alembic inspection callbacks, inside DB-enforced read-only mode."""
    if not isinstance(callback, FunctionType) or callback.__code__ not in _INSPECTION_CALLBACKS:
        raise MigrationAdmissionError("DENIED_OPERATION_UNPROVEN")
    with connection.begin():
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA query_only=ON")
        elif connection.dialect.name == "postgresql":
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        else:
            raise MigrationAdmissionError("DENIED_DATABASE_DIALECT_UNPROVEN")
        yield
