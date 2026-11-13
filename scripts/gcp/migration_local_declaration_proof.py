"""Bounded table declarations exclude unproved callbacks and external dependencies."""

from __future__ import annotations

import ast
import re

from gcp.migration_column_keyword_scan import literal_column_keywords
from gcp.migration_column_shape_proof import column_shape_failure
from gcp.migration_foreign_key_proof import constructor_foreign_key_failure, sa_constructor
from gcp.migration_numeric_default_proof import unproven_numeric_server_default

_LOCAL_CHECK = re.compile(
    r"(?:1\s*=\s*1|[A-Za-z_][A-Za-z_0-9]*\s*(?:IS\s+(?:NOT\s+)?NULL|(?:=|!=|<>|<=|>=|<|>)\s*-?[0-9]+(?:\.[0-9]+)?))",
    re.I,
)


def check_expression_failure(value: ast.expr | None) -> str | None:
    if (
        not isinstance(value, ast.Constant)
        or not isinstance(value.value, str)
        or _LOCAL_CHECK.fullmatch(value.value.strip()) is None
    ):
        return "CHECK expression has no local-effect proof"
    return None


def _column_failure(column: ast.Call, created: frozenset[str]) -> str | None:
    keys = literal_column_keywords(column)
    if keys is None:
        return "unverified new-table Column keyword binding"
    if problem := column_shape_failure(column, keys):
        return problem
    for item in column.args:
        if (
            isinstance(item, ast.Call)
            and sa_constructor(item) in {"ForeignKey", "CheckConstraint"}
            and (problem := local_declaration_failure(item, created))
        ):
            return problem
    return unproven_numeric_server_default(column, keys)


def local_declaration_failure(node: ast.expr, created: frozenset[str]) -> str | None:
    if not isinstance(node, ast.Call):
        return "unverified create_table declaration binding"
    name = sa_constructor(node)
    if name == "Column":
        return _column_failure(node, created)
    if name in {"ForeignKey", "ForeignKeyConstraint"}:
        return constructor_foreign_key_failure(node, created)
    if name == "CheckConstraint":
        keys = literal_column_keywords(node)
        value = node.args[0] if node.args else (keys or {}).get("sqltext")
        return check_expression_failure(value)
    if name in {"PrimaryKeyConstraint", "UniqueConstraint"} and all(
        isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.args
    ):
        return None
    return "create_table declaration has no local-effect proof"
