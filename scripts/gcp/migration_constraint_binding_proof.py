"""Validate every index/constraint binding before any local-effect admission."""

from __future__ import annotations

import ast

from gcp.migration_literal_bindings import (
    bound_arguments,
    literal_name,
    literal_names,
    literal_options,
)

_SIGNATURES = {
    "create_index": ("index_name", "table_name", "columns"),
    "create_unique_constraint": ("constraint_name", "table_name", "columns"),
    "create_check_constraint": ("constraint_name", "table_name", "condition"),
    "create_foreign_key": (
        "constraint_name",
        "source_table",
        "referent_table",
        "local_cols",
        "remote_cols",
    ),
}
_COLLECTIONS = frozenset({"columns", "local_cols", "remote_cols"})


def constraint_bindings(call: ast.Call, name: str) -> dict[str, ast.expr] | None:
    optional = frozenset({"unique"}) if name == "create_index" else frozenset()
    keys = bound_arguments(call, _SIGNATURES[name], optional)
    if keys is None or not literal_options(keys, flags=optional):
        return None
    for key in _SIGNATURES[name]:
        valid = literal_names(keys[key]) if key in _COLLECTIONS else literal_name(keys[key])
        if not valid:
            return None
    return keys
