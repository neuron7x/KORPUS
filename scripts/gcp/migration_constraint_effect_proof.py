"""Separate operation binding from local constraint-effect proof."""

from __future__ import annotations

import ast

from gcp.migration_foreign_key_proof import operation_foreign_key_failure
from gcp.migration_local_declaration_proof import check_expression_failure


def operation_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.attr if func.value.id == "op" else None
    return None


def constraint_keywords(call: ast.Call) -> dict[str, ast.expr] | None:
    found: dict[str, ast.expr] = {}
    for item in call.keywords:
        key = item.arg
        if key is None or key in found or key in {"schema", "source_schema"}:
            return None
        found[key] = item.value
    return found


def constraint_effect_failure(
    call: ast.Call, name: str, keys: dict[str, ast.expr], created: frozenset[str]
) -> str | None:
    if name == "create_foreign_key":
        return operation_foreign_key_failure(call, created)
    if name == "create_check_constraint":
        condition = call.args[2] if len(call.args) > 2 else keys.get("condition")
        return check_expression_failure(condition)
    return None
