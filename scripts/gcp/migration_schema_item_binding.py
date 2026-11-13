"""Supported constraint constructors have explicit literal bindings and no extra options."""

from __future__ import annotations

import ast

from gcp.migration_column_keyword_scan import literal_column_keywords
from gcp.migration_foreign_key_proof import sa_constructor
from gcp.migration_literal_bindings import (
    bound_arguments,
    literal_name,
    literal_options,
)
from gcp.migration_paired_column_proof import named_signature_values

_SIGNATURES = {
    "ForeignKey": ("column",),
    "ForeignKeyConstraint": ("columns", "refcolumns"),
    "CheckConstraint": ("sqltext",),
}
_COLLECTIONS = frozenset({"columns", "refcolumns"})


def schema_item_binding_failure(call: ast.Call) -> str | None:
    name = sa_constructor(call)
    if name in {"PrimaryKeyConstraint", "UniqueConstraint"}:
        keys = literal_column_keywords(call)
        if (
            keys is not None
            and keys.keys() <= {"name"}
            and literal_options(keys, strings=frozenset({"name"}))
            and call.args
            and all(literal_name(item) for item in call.args)
        ):
            return None
    elif name in _SIGNATURES:
        keys = bound_arguments(call, _SIGNATURES[name], frozenset({"name"}))
        if named_signature_values(keys, _SIGNATURES[name], _COLLECTIONS):
            return None
    return "unverified constraint constructor argument or keyword effects"


def column_schema_items_failure(items: list[ast.expr]) -> str | None:
    for item in items:
        if not isinstance(item, ast.Call) or sa_constructor(item) not in {
            "ForeignKey",
            "CheckConstraint",
        }:
            return "unverified Column schema item or positional binding"
        if problem := schema_item_binding_failure(item):
            return problem
    return None
