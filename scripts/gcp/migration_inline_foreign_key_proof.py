"""Inline foreign keys require independently new source and referent tables."""

from __future__ import annotations

import ast

from gcp.migration_column_target_proof import column_target_failure
from gcp.migration_foreign_key_proof import column_foreign_keys, constructor_foreign_key_failure


def inline_foreign_key_failure(
    call: ast.Call, column: ast.Call, keywords: dict[str, ast.expr], created: frozenset[str]
) -> str | None:
    foreign_keys = column_foreign_keys(column)
    if not foreign_keys:
        return None
    if problem := column_target_failure(call, created, "FOREIGN KEY"):
        return problem
    for foreign_key in foreign_keys:
        if problem := constructor_foreign_key_failure(foreign_key, created):
            return problem
    return None
