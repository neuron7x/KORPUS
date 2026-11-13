"""Bind the supported Column name, type, and explicit constraint forms only."""

from __future__ import annotations

import ast

from gcp.migration_column_keyword_effects import column_keyword_effects
from gcp.migration_column_type_proof import column_type_failure
from gcp.migration_foreign_key_proof import sa_constructor
from gcp.migration_schema_item_binding import column_schema_items_failure


def column_shape_failure(column: ast.Call, keys: dict[str, ast.expr]) -> str | None:
    if problem := column_keyword_effects(keys):
        return problem
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
    return column_schema_items_failure(args)
