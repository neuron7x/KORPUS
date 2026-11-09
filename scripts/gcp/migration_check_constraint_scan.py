"""Fail closed on inline CHECKs without a proof for existing populated rows."""

from __future__ import annotations

import ast
import re


def _is_check(item: ast.Call) -> bool:
    func = item.func
    if isinstance(func, ast.Name):
        return func.id == "CheckConstraint"
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "sa"
        and func.attr == "CheckConstraint"
    )


def _null_compatible(sql: str, name: object) -> bool:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
        return False
    identifier = re.escape(name)
    nullable = rf"{identifier}\s+IS\s+NULL"
    comparison = rf"{identifier}\s*(?:=|!=|<>|<|<=|>|>=)\s*-?\d+(?:\.\d+)?"
    return bool(
        re.fullmatch(nullable, sql, flags=re.I)
        or re.fullmatch(comparison, sql, flags=re.I)
        or re.fullmatch(rf"{nullable}\s+OR\s+{comparison}", sql, flags=re.I)
    )


def inline_check_failure(column: ast.Call, keywords: dict[str, ast.expr]) -> str | None:
    """Prove literal CHECK true/unknown for existing NULL rows; deny unknown SQL."""
    name = (
        column.args[0].value if column.args and isinstance(column.args[0], ast.Constant) else None
    )
    for item in column.args[1:]:
        if isinstance(item, ast.Starred):
            return "unverified Column positional expansion"
        if not isinstance(item, ast.Call) or not _is_check(item):
            continue
        if (
            len(item.args) != 1
            or not isinstance(item.args[0], ast.Constant)
            or not isinstance(item.args[0].value, str)
        ):
            return "unverified inline CheckConstraint expression"
        sql = item.args[0].value.strip()
        if re.fullmatch(r"1\s*=\s*1", sql):
            continue
        # A server default populates old rows: NULL-only reasoning is invalid.
        if "server_default" in keywords:
            return "inline CheckConstraint with unverified populated default"
        if not _null_compatible(sql, name):
            return "unproven NULL compatibility of inline CheckConstraint"
    return None
