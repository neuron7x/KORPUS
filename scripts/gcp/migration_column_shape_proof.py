"""Bind the supported Column name, type, and explicit constraint forms only."""

from __future__ import annotations

import ast

from gcp.migration_column_type_proof import column_type_failure
from gcp.migration_foreign_key_proof import sa_constructor

_COLUMN_KEYS = frozenset(
    {
        "name",
        "type_",
        "nullable",
        "primary_key",
        "unique",
        "index",
        "server_default",
        "autoincrement",
        "comment",
    }
)


def column_shape_failure(column: ast.Call, keys: dict[str, ast.expr]) -> str | None:
    if not keys.keys() <= _COLUMN_KEYS:
        return "unverified Column keyword effects"
    args = list(column.args)
    name = keys.get("name")
    if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
        if name is not None:
            return "duplicate Column name binding"
        name = args.pop(0)
    if not isinstance(name, ast.Constant) or not isinstance(name.value, str) or not name.value:
        return "unverified Column name binding"
    kind = keys.get("type_")
    if args and sa_constructor(args[0]) not in {"ForeignKey", "CheckConstraint"}:
        if kind is not None:
            return "duplicate Column type binding"
        kind = args.pop(0)
    if problem := column_type_failure(kind):
        return problem
    for item in args:
        if not isinstance(item, ast.Call) or sa_constructor(item) not in {
            "ForeignKey",
            "CheckConstraint",
        }:
            return "unverified Column schema item or positional binding"
    return None
