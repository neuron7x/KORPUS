"""Deny inline UNIQUE on unproven tables while preserving new-table DDL."""

from __future__ import annotations

import ast

from gcp.migration_column_target_proof import column_target_failure


def inline_unique_failure(
    call: ast.Call, keywords: dict[str, ast.expr], created: frozenset[str]
) -> str | None:
    flag = keywords.get("unique")
    if flag is None:
        return None
    if not isinstance(flag, ast.Constant) or type(flag.value) not in (bool, type(None)):
        return "unverified inline Column unique flag"
    if flag.value is not True:
        return None
    return column_target_failure(call, created, "UNIQUE")
