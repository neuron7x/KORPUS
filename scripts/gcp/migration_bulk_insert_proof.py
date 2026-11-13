"""Bulk rows may target only proven-new tables through literal bind values."""

from __future__ import annotations

import ast
import math

from gcp.migration_foreign_key_proof import sa_constructor
from gcp.migration_literal_bindings import bound_arguments, literal_name, literal_options


def _table_columns(table: ast.expr, created: frozenset[str]) -> set[str] | None:
    if (
        not isinstance(table, ast.Call)
        or sa_constructor(table) != "table"
        or table.keywords
        or len(table.args) < 2
    ):
        return None
    name = table.args[0]
    if not literal_name(name) or getattr(name, "value", None) not in created:
        return None
    columns: set[str] = set()
    for item in table.args[1:]:
        if (
            not isinstance(item, ast.Call)
            or sa_constructor(item) != "column"
            or item.keywords
            or len(item.args) != 1
        ):
            return None
        value = item.args[0]
        column_name = getattr(value, "value", None)
        if not isinstance(column_name, str) or not literal_name(value):
            return None
        columns.add(column_name)
    return columns


def _literal_rows(rows: ast.expr, columns: set[str]) -> bool:
    try:
        values = ast.literal_eval(rows)
    except (ValueError, TypeError):
        return False
    if not isinstance(values, list):
        return False
    for row in values:
        if not isinstance(row, dict) or not row.keys() <= columns:
            return False
        for value in row.values():
            if type(value) not in (str, int, float, bool, type(None)):
                return False
            if isinstance(value, float) and not math.isfinite(value):
                return False
    return True


def bulk_insert_failure(call: ast.Call, created: frozenset[str]) -> str | None:
    keys = bound_arguments(call, ("table", "rows"), frozenset({"multiinsert"}))
    if keys is None or not literal_options(keys, flags=frozenset({"multiinsert"})):
        return "unverified bulk_insert argument or keyword binding"
    columns = _table_columns(keys["table"], created)
    if columns is None or not _literal_rows(keys["rows"], columns):
        return "bulk_insert requires a proven-new table and literal bound rows"
    return None
