"""Literal, duplicate-free argument bindings shared by bounded operation proofs."""

from __future__ import annotations

import ast

from gcp.migration_column_keyword_scan import literal_column_keywords


def bound_arguments(
    call: ast.Call, positional: tuple[str, ...], optional: frozenset[str] = frozenset()
) -> dict[str, ast.expr] | None:
    keys = literal_column_keywords(call)
    if (
        keys is None
        or len(call.args) > len(positional)
        or not keys.keys() <= set(positional) | optional
    ):
        return None
    result = dict(keys)
    for name, value in zip(positional, call.args, strict=False):
        if name in result or isinstance(value, ast.Starred):
            return None
        result[name] = value
    return result if set(positional) <= result.keys() else None


def literal_name(node: ast.expr | None) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and bool(node.value)
        and "\0" not in node.value
    )


def literal_names(node: ast.expr | None) -> bool:
    return (
        isinstance(node, (ast.List, ast.Tuple))
        and bool(node.elts)
        and all(literal_name(item) for item in node.elts)
    )


def literal_options(
    keys: dict[str, ast.expr],
    *,
    strings: frozenset[str] = frozenset(),
    flags: frozenset[str] = frozenset(),
) -> bool:
    for name in strings & keys.keys():
        value = keys[name]
        if not literal_name(value) and not (
            isinstance(value, ast.Constant) and value.value is None
        ):
            return False
    for name in flags & keys.keys():
        value = keys[name]
        if not isinstance(value, ast.Constant) or type(value.value) is not bool:
            return False
    return True
