from __future__ import annotations

import ast
import re

from gcp.migration_numeric_default_proof import _FLOATS, _INTEGERS


def _is_check(item: ast.Call) -> bool:
    func = item.func
    return (isinstance(func, ast.Name) and func.id == "CheckConstraint") or (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "sa"
        and func.attr == "CheckConstraint"
    )


def _null_compatible(sql: str, column: ast.Call) -> bool:
    name = getattr(column.args[0], "value", None) if column.args else None
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
        return False
    func = getattr(column.args[1], "func", None) if len(column.args) > 1 else None
    numeric = (
        getattr(func, "attr", None) in _INTEGERS | _FLOATS
        and getattr(getattr(func, "value", None), "id", None) == "sa"
    )
    identifier = re.escape(name)
    nullable = rf"{identifier}\s+IS\s+NULL"
    comparison = rf"{identifier}\s*(?:=|!=|<>|<|<=|>|>=)\s*-?\d+(?:\.\d+)?"
    patterns = [nullable]
    if numeric:
        patterns.extend((comparison, rf"{nullable}\s+OR\s+{comparison}"))
    return any(re.fullmatch(pattern, sql, flags=re.I) for pattern in patterns)


def inline_check_failure(column: ast.Call, keywords: dict[str, ast.expr]) -> str | None:
    """Prove literal CHECK true/unknown for existing NULL rows; deny unknown SQL."""
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
        if "server_default" in keywords:
            return "inline CheckConstraint with unverified populated default"
        if not _null_compatible(sql, column):
            return "unproven NULL compatibility of inline CheckConstraint"
    return None
