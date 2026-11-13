"""Finite namespace diagnostics never serialize arbitrary migration expressions."""

from __future__ import annotations

import ast
from enum import Enum, auto


class NamespaceIssue(Enum):
    ESCAPED = auto()
    MUTATION = auto()
    INTROSPECTION = auto()
    OPERATION_ESCAPE = auto()
    CALLBACK = auto()


NAMESPACE_MESSAGES = {
    NamespaceIssue.ESCAPED: "trusted namespace escaped",
    NamespaceIssue.MUTATION: "trusted namespace mutation",
    NamespaceIssue.INTROSPECTION: "trusted namespace introspection/mutation",
    NamespaceIssue.OPERATION_ESCAPE: "trusted operation callable escaped",
    NamespaceIssue.CALLBACK: "unverified named callback binding",
}


def callback_issue(node: ast.AST) -> NamespaceIssue | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return None
    if node.func.id not in {"sorted", "min", "max"}:
        return None
    for keyword in node.keywords:
        if keyword.arg == "key" and not isinstance(keyword.value, (ast.Lambda, ast.Constant)):
            return NamespaceIssue.CALLBACK
    return None
