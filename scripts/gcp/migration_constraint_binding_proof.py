"""Validate every index/constraint binding before any local-effect admission."""

from __future__ import annotations

import ast

from gcp.migration_literal_bindings import (
    bound_arguments,
    literal_options,
)
from gcp.migration_paired_column_proof import literal_signature_values

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
    return keys if literal_signature_values(keys, _SIGNATURES[name], _COLLECTIONS) else None
