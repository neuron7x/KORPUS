"""Do not narrow N-1 writes with new constraints on existing tables."""

from __future__ import annotations

import ast

_RESTRICTIVE = frozenset(
    {"create_unique_constraint", "create_check_constraint", "create_foreign_key"}
)


def _operation(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.attr if func.value.id == "op" else None
    return None


def _keywords(call: ast.Call) -> dict[str, ast.expr] | None:
    found: dict[str, ast.expr] = {}
    for item in call.keywords:
        key = item.arg
        if key is None or key in found or key in {"schema", "source_schema"}:
            return None
        found[key] = item.value
    return found


def constraint_failure(call: ast.Call, created: frozenset[str]) -> str | None:
    """Admit restrictive DDL only for tables proven new on every execution path."""
    name = _operation(call)
    if name not in _RESTRICTIVE | {"create_index"}:
        return None
    keys = _keywords(call)
    if keys is None:
        return f"unverified op.{name} keyword binding"
    if name == "create_index":
        if len(call.args) > 3:
            return "unverified create_index positional binding"
        unique = keys.get("unique", ast.Constant(value=False))
        if not isinstance(unique, ast.Constant) or type(unique.value) is not bool:
            return "unverified create_index unique flag"
        if unique.value is False:
            return None
    key = "source_table" if name == "create_foreign_key" else "table_name"
    if len(call.args) > 1 and key in keys:
        return f"duplicate op.{name} table binding"
    table = call.args[1] if len(call.args) > 1 else keys.get(key)
    if not isinstance(table, ast.Constant) or not isinstance(table.value, str):
        return f"unverified op.{name} table name"
    if table.value not in created:
        return f"op.{name} restricts existing or unproven table: {table.value}"
    return None
