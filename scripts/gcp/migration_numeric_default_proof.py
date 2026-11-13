"""Prove supported populated defaults; unsupported type/default combinations deny."""

from __future__ import annotations

import ast

from gcp.migration_default_type_bounds import (
    INTEGER_TYPES,
    NUMERIC_TYPES,
    STRING_TYPES,
    bounded_default_valid,
)
from gcp.migration_scalar_default_proof import literal_default, none_default

_INTEGERS, _FLOATS = INTEGER_TYPES, NUMERIC_TYPES


def nonnullable_add_without_default(keywords: dict[str, ast.expr]) -> bool:
    nullable, default = keywords.get("nullable"), keywords.get("server_default")
    no_server_default = default is None or literal_default(default) is None
    if nullable is None and (primary_key := keywords.get("primary_key")) is not None:
        nullable = ast.Constant(value=getattr(primary_key, "value", None) is False)
    is_nullable = isinstance(nullable, ast.Constant) and nullable.value is True
    return nullable is not None and not is_nullable and no_server_default


def unproven_numeric_server_default(column: ast.Call, keywords: dict[str, ast.expr]) -> str | None:
    if "server_default" not in keywords:
        return None
    type_index = 0 if "name" in keywords else 1
    type_node = column.args[type_index] if len(column.args) > type_index else keywords.get("type_")
    if type_node is None or (len(column.args) > type_index) == ("type_" in keywords):
        return "unverified or ambiguous Column type binding"
    constructor = type_node.func if isinstance(type_node, ast.Call) else type_node
    if isinstance(constructor, ast.Attribute) and getattr(constructor.value, "id", None) == "sa":
        name: str | None = constructor.attr
    else:
        name = getattr(constructor, "id", None)
    default = keywords["server_default"]
    if none_default(default, allow_expression=name in STRING_TYPES):
        return None
    literal = literal_default(default)
    if literal is None:
        return "server_default requires a proven literal value"
    if name is None or not bounded_default_valid(type_node, name, literal):
        return f"literal server_default is incompatible or unproven for {name}"
    return None
