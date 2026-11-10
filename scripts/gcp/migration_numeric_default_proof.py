"""Conservative literal numeric-default check for additions to populated tables."""

from __future__ import annotations

import ast
import re

_INTEGERS = frozenset(
    {"Integer", "BigInteger", "SmallInteger", "INTEGER", "BIGINT", "SMALLINT", "INT"}
)
_FLOATS = frozenset({"Float", "REAL", "Numeric", "DECIMAL", "NUMERIC", "FLOAT", "DOUBLE_PRECISION"})
_INT_LITERAL = re.compile(r"[+-]?[0-9]+\Z")
_FLOAT_LITERAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?\Z")


def nonnullable_add_without_default(keywords: dict[str, ast.expr]) -> bool:
    nullable, default = keywords.get("nullable"), keywords.get("server_default")
    primary_key = keywords.get("primary_key")
    no_server_default = not (isinstance(default, ast.Constant) and isinstance(default.value, str))
    if nullable is None and primary_key is not None:
        nullable = ast.Constant(
            value=isinstance(primary_key, ast.Constant) and primary_key.value is False
        )
    return (
        nullable is not None
        and not (isinstance(nullable, ast.Constant) and nullable.value is True)
        and no_server_default
    )


def unproven_numeric_server_default(column: ast.Call, keywords: dict[str, ast.expr]) -> str | None:
    """Fail closed for uncastable numeric defaults; absence of default stays valid."""
    if len(column.args) < 2 or "server_default" not in keywords:
        return None
    type_node = column.args[1]
    constructor = type_node.func if isinstance(type_node, ast.Call) else type_node
    if isinstance(constructor, ast.Attribute) and isinstance(constructor.value, ast.Name):
        name = constructor.attr if constructor.value.id == "sa" else None
    else:
        name = constructor.id if isinstance(constructor, ast.Name) else None
    if name not in _INTEGERS | _FLOATS:
        return None
    default = keywords["server_default"]
    if isinstance(default, ast.Constant) and default.value is None:
        return None
    pattern = _INT_LITERAL if name in _INTEGERS else _FLOAT_LITERAL
    if not isinstance(default, ast.Constant) or not isinstance(default.value, str):
        return "numeric server_default requires a proven literal value"
    if not pattern.fullmatch(default.value):
        return f"numeric server_default is incompatible with {name}"
    return None
