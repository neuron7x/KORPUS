"""Literal Alembic add_column binding; reject dynamic or colliding arguments."""

from __future__ import annotations

import ast

from gcp.migration_column_keyword_scan import literal_column_keywords


def bind_add_column_argument(call: ast.Call) -> tuple[ast.expr | None, str | None]:
    """Recover an exact column argument or fail closed on unknown call binding."""
    if len(call.args) > 2 or any(isinstance(arg, ast.Starred) for arg in call.args):
        return None, "unverified add_column positional arguments"
    keywords = literal_column_keywords(call)
    if keywords is None:
        return None, "unverified add_column keyword expansion or duplicate keys"
    for position, name in enumerate(("table_name", "column")):
        if name in keywords and len(call.args) > position:
            return None, f"duplicate add_column {name} argument"
    if not call.args and "table_name" not in keywords:
        return None, "add_column missing table_name"
    column = call.args[1] if len(call.args) == 2 else keywords.get("column")
    if column is None:
        return None, "add_column missing column"
    return column, None
