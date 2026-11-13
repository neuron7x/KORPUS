"""Small positive proof domain for nonnumeric defaults; unknown values deny."""

from __future__ import annotations

import ast
import re


def _quoted_text(node: ast.expr) -> str | None:
    if not isinstance(node, ast.Call) or node.keywords or len(node.args) != 1:
        return None
    if not isinstance(node.func, ast.Attribute) or ast.unparse(node.func) != "sa.text":
        return None
    value = node.args[0]
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        return None
    # Backslash escapes depend on server configuration; only ordinary literals prove a value.
    if not re.fullmatch(r"'(?:[^'\\]|'')*'", value.value):
        return None
    return value.value[1:-1].replace("''", "'")


def literal_default(node: ast.expr) -> str | None:
    value = node.value if isinstance(node, ast.Constant) else _quoted_text(node)
    if not isinstance(value, str) or "\0" in value:
        return None
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return value


def none_default(node: ast.expr, *, allow_expression: bool) -> bool:
    if isinstance(node, ast.Constant):
        return node.value is None
    return (
        allow_expression
        and isinstance(node, ast.BoolOp)
        and all(none_default(value, allow_expression=True) for value in node.values)
    )


def simple_default_valid(node: ast.expr, name: str, literal: str) -> bool:
    if isinstance(node, ast.Call) and (node.args or node.keywords):
        return False
    if name in {"Text", "UnicodeText", "TEXT"}:
        return True
    if name in {"Boolean", "BOOLEAN"}:
        return literal.lower() in {"true", "false", "yes", "no", "on", "off", "1", "0"}
    if name == "JSON":
        return literal in {"{}", "[]"}
    return False
