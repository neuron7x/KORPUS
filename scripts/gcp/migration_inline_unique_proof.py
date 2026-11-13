"""Deny inline UNIQUE on unproven tables while preserving new-table DDL."""

from __future__ import annotations

import ast

from gcp.migration_column_keyword_scan import literal_column_keywords


def inline_unique_failure(
    call: ast.Call, keywords: dict[str, ast.expr], created: frozenset[str]
) -> str | None:
    flag = keywords.get("unique")
    if flag is None:
        return None
    if not isinstance(flag, ast.Constant) or type(flag.value) not in (bool, type(None)):
        return "unverified inline Column unique flag"
    if flag.value is not True:
        return None
    call_keywords = literal_column_keywords(call)
    if call_keywords is None:
        return "unverified add_column table binding"
    table = call.args[0] if call.args else call_keywords.get("table_name")
    if not isinstance(table, ast.Constant) or not isinstance(table.value, str):
        return "unverified add_column table for inline UNIQUE"
    if table.value not in created:
        return f"inline UNIQUE restricts existing or unproven table: {table.value}"
    return None
