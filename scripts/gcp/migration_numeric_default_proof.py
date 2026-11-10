"""Conservative literal numeric-default check for additions to populated tables."""

from __future__ import annotations

import ast
import re

_INTEGERS = frozenset(
    ["Integer", "BigInteger", "SmallInteger", "INTEGER", "BIGINT", "SMALLINT", "INT"]
)
_FLOATS = frozenset(
    ["Float", "REAL", "Numeric", "DECIMAL", "NUMERIC", "FLOAT", "DOUBLE_PRECISION"]
)
_INT_LITERAL = re.compile(r"[+-]?[0-9]{1,19}\Z")
_FLOAT_LITERAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?\Z")
_INTEGER_BITS = {"SmallInteger": 16, "SMALLINT": 16, "BigInteger": 64, "BIGINT": 64}


def nonnullable_add_without_default(keywords: dict[str, ast.expr]) -> bool:
    nullable, default = keywords.get("nullable"), keywords.get("server_default")
    no_server_default = not (isinstance(default, ast.Constant) and isinstance(default.value, str))
    if nullable is None and (primary_key := keywords.get("primary_key")) is not None:
        nullable = ast.Constant(value=getattr(primary_key, "value", None) is False)
    return (
        nullable is not None
        and not (isinstance(nullable, ast.Constant) and nullable.value is True)
        and no_server_default
    )


def _numeric_literal_valid(name: str, literal: str) -> bool:
    pattern = _INT_LITERAL if name in _INTEGERS else _FLOAT_LITERAL
    limit = 1 << (_INTEGER_BITS.get(name, 32) - 1)
    return bool(pattern.fullmatch(literal)) and (
        name not in _INTEGERS or -limit <= int(literal) < limit
    )


def unproven_numeric_server_default(column: ast.Call, keywords: dict[str, ast.expr]) -> str | None:
    if "server_default" not in keywords:
        return None
    type_node = column.args[1] if len(column.args) > 1 else keywords.get("type_")
    if type_node is None or (len(column.args) > 1) == ("type_" in keywords):
        return "unverified or ambiguous Column type binding"
    constructor = type_node.func if isinstance(type_node, ast.Call) else type_node
    if isinstance(constructor, ast.Attribute) and getattr(constructor.value, "id", None) == "sa":
        name: str | None = constructor.attr
    else:
        name = getattr(constructor, "id", None)
    if name is None or name not in _INTEGERS | _FLOATS:
        return None
    default = keywords["server_default"]
    if isinstance(default, ast.Constant) and default.value is None:
        return None
    if not isinstance(default, ast.Constant) or not isinstance(default.value, str):
        return "numeric server_default requires a proven literal value"
    if not _numeric_literal_valid(name, default.value):
        return f"numeric server_default is incompatible with {name}"
    return None
