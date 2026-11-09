"""Fail-closed checks for mutable Alembic and SQLAlchemy namespaces."""

from __future__ import annotations

import ast

_TRUSTED = frozenset({"op", "sa"})
_MUTATORS = frozenset({"__dict__", "__setattr__", "__delattr__"})


def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    if isinstance(node, ast.Name) and node.id in _TRUSTED:
        return node.id
    return None


def _unsafe_callback(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return None
    if node.func.id not in {"sorted", "min", "max"}:
        return None
    for keyword in node.keywords:
        if keyword.arg == "key" and not isinstance(keyword.value, (ast.Lambda, ast.Constant)):
            return "unverified named callback binding"
    return None


def _unsafe_binding(node: ast.AST, parent: ast.AST | None) -> str | None:
    if (
        isinstance(node, ast.Name)
        and node.id in _TRUSTED
        and isinstance(node.ctx, ast.Load)
        and not (isinstance(parent, ast.Attribute) and parent.value is node)
    ):
        return f"trusted namespace escaped: {node.id}"
    if isinstance(node, (ast.Attribute, ast.Subscript)):
        owner = _root_name(node)
        if owner and isinstance(node.ctx, (ast.Store, ast.Del)):
            return f"trusted namespace mutation: {owner}"
        if isinstance(node, ast.Attribute) and owner:
            if node.attr in _MUTATORS:
                return f"trusted namespace introspection/mutation: {owner}.{node.attr}"
            if owner == "op" and isinstance(node.ctx, ast.Load) and not (
                isinstance(parent, ast.Call)
                and parent.func is node
                or isinstance(parent, (ast.Attribute, ast.Subscript))
            ):
                return "trusted operation callable escaped"
    return _unsafe_callback(node)


def trusted_object_failures(statements: list[ast.stmt]) -> list[str]:
    """Audit executed scopes; reached helper bodies are inspected separately."""
    failures: list[str] = []
    pending: list[tuple[ast.AST, ast.AST | None]] = [(item, None) for item in statements]
    while pending:
        node, parent = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if (problem := _unsafe_binding(node, parent)) is not None:
            failures.append(problem)
        pending.extend((child, node) for child in ast.iter_child_nodes(node))
    return failures
