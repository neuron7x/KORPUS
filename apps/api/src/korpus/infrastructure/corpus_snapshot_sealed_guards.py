"""Install and verify the sealed-parent and provenance boundary from migration 0025."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Connection

from korpus.infrastructure.corpus_snapshot_sealed_sql import (
    POSTGRES_FUNCTIONS,
    POSTGRES_TRIGGERS,
    SQLITE_TRIGGERS,
)


def _normalized(source: object) -> str:
    return " ".join(str(source or "").lower().split())


def _function_body(source: str) -> str:
    body = source.split("$$")[1] if "$$" in source else source
    return _normalized(re.sub(r"--[^\n]*", " ", body))


def install_sealed_guards(connection: Connection) -> None:
    if connection.dialect.name == "sqlite":
        for statement in SQLITE_TRIGGERS.values():
            connection.exec_driver_sql(
                statement.replace("CREATE TRIGGER", "CREATE TRIGGER IF NOT EXISTS", 1)
            )
    elif connection.dialect.name == "postgresql":
        for name, statement in POSTGRES_FUNCTIONS.items():
            connection.exec_driver_sql(
                statement.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
            )
            connection.exec_driver_sql(f"REVOKE ALL ON FUNCTION public.{name}() FROM PUBLIC")
        for (table, name), statement in POSTGRES_TRIGGERS.items():
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON public.{table}")
            connection.exec_driver_sql(statement)
    else:
        raise RuntimeError(f"unsupported sealed guard dialect: {connection.dialect.name}")


def _require_sqlite(connection: Connection) -> None:
    actual = {
        str(row[0]): str(row[1])
        for row in connection.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type='trigger'")
        ).all()
    }
    for name, expected in SQLITE_TRIGGERS.items():
        if name not in actual:
            raise RuntimeError(f"corpus snapshot guards are missing: {name}")
        if _normalized(actual[name]) != _normalized(expected):
            raise RuntimeError(f"corpus snapshot guard {name} has invalid definition")


def _require_postgres_triggers(connection: Connection) -> None:
    rows = connection.execute(
        text(
            "SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid), fn.nspname, p.proname "
            "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace fn ON fn.oid=p.pronamespace "
            "WHERE NOT t.tgisinternal AND t.tgenabled IN ('O','A') AND n.nspname='public'"
        )
    ).all()
    actual = {(str(r[0]), str(r[1])): (str(r[2]), str(r[3]), str(r[4])) for r in rows}
    for key, expected in POSTGRES_TRIGGERS.items():
        if key not in actual:
            raise RuntimeError(f"corpus snapshot guards are missing: {key[1]}")
        definition, namespace, function = actual[key]
        if namespace != "public" or f"public.{function}()" not in expected:
            raise RuntimeError(f"corpus snapshot guard {key[1]} has invalid function binding")
        if _normalized(definition).replace("public.", "") != _normalized(expected).replace(
            "public.", ""
        ):
            raise RuntimeError(f"corpus snapshot guard {key[1]} has invalid definition")


def _require_postgres_functions(connection: Connection) -> None:
    rows = connection.execute(
        text(
            "SELECT p.proname, p.prosecdef, p.proconfig, p.prosrc, "
            "EXISTS (SELECT 1 FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) a "
            "WHERE a.grantee=0 AND a.privilege_type='EXECUTE') "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.pronargs=0 AND p.prorettype='trigger'::regtype"
        )
    ).all()
    actual = {str(r[0]): r for r in rows}
    for name, expected in POSTGRES_FUNCTIONS.items():
        if name not in actual:
            raise RuntimeError(f"corpus snapshot guard function is missing: {name}")
        _, definer, config, body, public_execute = actual[name]
        expected_definer = "SECURITY DEFINER" in expected
        paths = {_normalized(item).replace(" ", "") for item in (config or ())}
        if (
            bool(definer) != expected_definer
            or "search_path=pg_catalog,public" not in paths
            or public_execute
        ):
            raise RuntimeError(f"corpus snapshot guard function is not hardened: {name}")
        if _function_body(str(body)) != _function_body(expected):
            raise RuntimeError(f"corpus snapshot guard {name} has invalid function body")


def require_sealed_guards(connection: Connection) -> None:
    if connection.dialect.name == "sqlite":
        _require_sqlite(connection)
    elif connection.dialect.name == "postgresql":
        _require_postgres_triggers(connection)
        _require_postgres_functions(connection)
    else:
        raise RuntimeError(f"unsupported sealed guard dialect: {connection.dialect.name}")
