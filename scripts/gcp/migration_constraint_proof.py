"""Do not narrow N-1 writes with new constraints on existing tables."""

from __future__ import annotations

import ast

from gcp.migration_constraint_binding_proof import constraint_bindings
from gcp.migration_constraint_effect_proof import constraint_effect_failure
from gcp.migration_constraint_effect_proof import operation_name as _operation

_RESTRICTIVE = frozenset(
    {"create_unique_constraint", "create_check_constraint", "create_foreign_key"}
)


def constraint_failure(call: ast.Call, created: frozenset[str]) -> str | None:
    """Admit restrictive DDL only for tables proven new on every execution path."""
    name = _operation(call)
    if name not in _RESTRICTIVE | {"create_index"}:
        return None
    keys = constraint_bindings(call, name)
    if keys is None:
        return f"unverified op.{name} argument or keyword binding"
    if name == "create_index" and getattr(keys.get("unique"), "value", False) is False:
        return None
    key = "source_table" if name == "create_foreign_key" else "table_name"
    table = getattr(keys[key], "value", None)
    if table not in created:
        return f"op.{name} restricts existing or unproven table: {table}"
    return constraint_effect_failure(call, name, keys, created)
