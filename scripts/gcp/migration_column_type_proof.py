"""Bounded type constructors; never interpolate unknown DDL parameter values."""

from __future__ import annotations

import ast

from gcp.migration_column_keyword_scan import literal_column_keywords
from gcp.migration_default_type_bounds import (
    INTEGER_TYPES,
    NUMERIC_TYPES,
    STRING_TYPES,
    _parameters,
)
from gcp.migration_foreign_key_proof import sa_constructor

_BARE = frozenset(
    {
        "Text",
        "UnicodeText",
        "TEXT",
        "Boolean",
        "BOOLEAN",
        "Date",
        "DATE",
        "LargeBinary",
        "BINARY",
        "VARBINARY",
    }
)
_FLAGS = {
    "DateTime": "timezone",
    "TIMESTAMP": "timezone",
    "Time": "timezone",
    "TIME": "timezone",
    "JSON": "none_as_null",
}


def _bounded_parameters(node: ast.expr, name: str) -> bool:
    if name in STRING_TYPES:
        values = _parameters(node, ("length",))
        return values is not None and (values["length"] is None or 0 < values["length"] <= 10485760)
    if name in {"Numeric", "DECIMAL", "NUMERIC"}:
        values = _parameters(node, ("precision", "scale"))
        return (
            values is not None
            and (values["precision"] is None or 1 <= values["precision"] <= 1000)
            and (values["scale"] is None or -1000 <= values["scale"] <= 1000)
        )
    values = _parameters(node, ("precision",))
    return values is not None and (values["precision"] is None or 1 <= values["precision"] <= 53)


def column_type_failure(node: ast.expr | None) -> str | None:
    name = sa_constructor(node) if node is not None else None
    if (
        name is None
        or name not in INTEGER_TYPES | NUMERIC_TYPES | STRING_TYPES | _BARE | _FLAGS.keys()
    ):
        return "unverified Column type constructor"
    if not isinstance(node, ast.Call):
        return None
    if name in NUMERIC_TYPES | STRING_TYPES:
        return None if _bounded_parameters(node, name) else "unverified Column type parameters"
    keys = literal_column_keywords(node)
    if node.args or keys is None:
        return "unverified Column type parameters"
    if not keys:
        return None
    if name in _FLAGS and keys.keys() == {_FLAGS[name]}:
        value = keys[_FLAGS[name]]
        if isinstance(value, ast.Constant) and type(value.value) is bool:
            return None
    return "unverified Column type keyword parameters"
