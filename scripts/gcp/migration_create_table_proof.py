"""Prove independent CREATE TABLE bindings; dialect and dynamic effects deny."""

from __future__ import annotations

import ast

from gcp.migration_column_keyword_scan import literal_column_keywords
from gcp.migration_literal_bindings import literal_options
from gcp.migration_local_declaration_proof import local_declaration_failure


def _is_create(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and getattr(func.value, "id", None) == "op"
        and func.attr == "create_table"
    )


def _table_name(call: ast.Call, keys: dict[str, ast.expr]) -> str | None:
    if call.args and "table_name" in keys:
        return None
    table = call.args[0] if call.args else keys.get("table_name")
    return table.value if isinstance(table, ast.Constant) and isinstance(table.value, str) else None


def created_table_name(call: ast.Call) -> str | None:
    if not _is_create(call):
        return None
    keys = literal_column_keywords(call)
    if keys is None or not keys.keys() <= {"table_name"}:
        return None
    return _table_name(call, keys)


def create_table_failure(call: ast.Call, created: frozenset[str]) -> str | None:
    if not _is_create(call):
        return None
    keys = literal_column_keywords(call)
    if keys is None or not keys.keys() <= {"table_name", "schema", "if_not_exists"}:
        return "create_table dialect or dynamic options have no local-effect proof"
    name = _table_name(call, keys)
    if name is None:
        return "unverified create_table name binding"
    if not literal_options(keys, strings=frozenset({"schema"}), flags=frozenset({"if_not_exists"})):
        return "unverified create_table scope binding"
    local = created | {name} if created_table_name(call) is not None else frozenset()
    for declaration in call.args[1:]:
        if problem := local_declaration_failure(declaration, local):
            return problem
    return None
