"""Bind a restrictive inline constraint to a proven new unqualified table."""

from __future__ import annotations

import ast

from gcp.migration_column_keyword_scan import literal_column_keywords


def column_target_failure(call: ast.Call, created: frozenset[str], kind: str) -> str | None:
    keywords = literal_column_keywords(call)
    if keywords is None or "schema" in keywords:
        return f"unverified add_column table or schema binding for inline {kind}"
    table = call.args[0] if call.args else keywords.get("table_name")
    if not isinstance(table, ast.Constant) or not isinstance(table.value, str):
        return f"unverified add_column table for inline {kind}"
    if table.value not in created:
        return f"inline {kind} restricts existing or unproven table"
    return None
