"""Closed literal value domains for Column metadata and behavioral flags."""

from __future__ import annotations

import ast

_KEYS = frozenset(
    {
        "name",
        "type_",
        "nullable",
        "primary_key",
        "unique",
        "index",
        "server_default",
        "autoincrement",
        "comment",
    }
)


def _flag_valid(key: str, value: ast.expr) -> bool:
    return isinstance(value, ast.Constant) and (
        type(value.value) is bool or (key in {"unique", "index"} and value.value is None)
    )


def _autoincrement_valid(value: ast.expr) -> bool:
    return isinstance(value, ast.Constant) and (
        type(value.value) is bool
        or (type(value.value) is str and value.value in {"auto", "ignore_fk"})
    )


def column_keyword_effects(keys: dict[str, ast.expr]) -> str | None:
    if not keys.keys() <= _KEYS:
        return "unverified Column keyword effects"
    for key in {"nullable", "primary_key", "unique", "index"} & keys.keys():
        if not _flag_valid(key, keys[key]):
            return "unverified Column keyword flag for server_default compatibility"
    if "autoincrement" in keys and not _autoincrement_valid(keys["autoincrement"]):
        return "unverified Column autoincrement option"
    if "comment" in keys:
        value = keys["comment"]
        if not isinstance(value, ast.Constant) or type(value.value) not in (str, type(None)):
            return "unverified Column comment option"
    return None
