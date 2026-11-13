"""Literal FK column collections must form pairs with equal cardinality."""

from __future__ import annotations

import ast

from gcp.migration_literal_bindings import literal_name, literal_names, literal_options

_PAIRS = (("local_cols", "remote_cols"), ("columns", "refcolumns"))


def equal_length_name_collections(left: ast.expr, right: ast.expr) -> bool:
    return (
        isinstance(left, (ast.List, ast.Tuple))
        and isinstance(right, (ast.List, ast.Tuple))
        and literal_names(left)
        and literal_names(right)
        and len(left.elts) == len(right.elts)
    )


def literal_signature_values(
    keys: dict[str, ast.expr], signature: tuple[str, ...], collections: frozenset[str]
) -> bool:
    if not all(
        literal_names(keys[key]) if key in collections else literal_name(keys[key])
        for key in signature
    ):
        return False
    return all(
        equal_length_name_collections(keys[left], keys[right])
        for left, right in _PAIRS
        if left in keys and right in keys
    )


def named_signature_values(
    keys: dict[str, ast.expr] | None, signature: tuple[str, ...], collections: frozenset[str]
) -> bool:
    return (
        keys is not None
        and literal_options(keys, strings=frozenset({"name"}))
        and literal_signature_values(keys, signature, collections)
    )
