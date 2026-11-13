"""Argument proof for admitted operations outside the constraint/DDL handlers."""

from __future__ import annotations

import ast

from gcp.migration_bulk_insert_proof import bulk_insert_failure
from gcp.migration_constraint_effect_proof import operation_name
from gcp.migration_literal_bindings import bound_arguments, literal_name, literal_options


def operation_argument_failure(call: ast.Call, created: frozenset[str]) -> str | None:
    name = operation_name(call)
    if name == "bulk_insert":
        return bulk_insert_failure(call, created)
    if name == "get_bind":
        return "get_bind accepts no arguments" if call.args or call.keywords else None
    if name != "add_column":
        return None
    keys = bound_arguments(call, ("table_name", "column"), frozenset({"schema", "if_not_exists"}))
    if (
        keys is None
        or not literal_name(keys["table_name"])
        or not literal_options(
            keys, strings=frozenset({"schema"}), flags=frozenset({"if_not_exists"})
        )
    ):
        return "unverified add_column argument or keyword effects"
    return None
