"""Fail-closed checks for mutable Alembic and SQLAlchemy namespaces."""

from __future__ import annotations

import ast

from gcp.migration_namespace_diagnostics import NAMESPACE_MESSAGES, NamespaceIssue, callback_issue

_TRUSTED = frozenset({"op", "sa"})
_MUTATORS = frozenset({"__dict__", "__setattr__", "__delattr__"})


def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    if isinstance(node, ast.Name) and node.id in _TRUSTED:
        return node.id
    return None


def _unsafe_binding(node: ast.AST, parent: ast.AST | None) -> NamespaceIssue | None:
    if (
        isinstance(node, ast.Name)
        and node.id in _TRUSTED
        and isinstance(node.ctx, ast.Load)
        and not (isinstance(parent, ast.Attribute) and parent.value is node)
    ):
        return NamespaceIssue.ESCAPED
    if isinstance(node, (ast.Attribute, ast.Subscript)):
        owner = _root_name(node)
        if owner and isinstance(node.ctx, (ast.Store, ast.Del)):
            return NamespaceIssue.MUTATION
        if isinstance(node, ast.Attribute) and owner:
            if node.attr in _MUTATORS:
                return NamespaceIssue.INTROSPECTION
            called = isinstance(parent, ast.Call) and parent.func is node
            chained = isinstance(parent, (ast.Attribute, ast.Subscript))
            if owner == "op" and isinstance(node.ctx, ast.Load) and not (called or chained):
                return NamespaceIssue.OPERATION_ESCAPE
    return callback_issue(node)


def namespace_violations(statements: list[ast.stmt]) -> list[NamespaceIssue]:
    """Audit executed scopes; reached helper bodies are inspected separately."""
    failures: list[NamespaceIssue] = []
    pending: list[tuple[ast.AST, ast.AST | None]] = [(item, None) for item in statements]
    while pending:
        node, parent = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if (problem := _unsafe_binding(node, parent)) is not None:
            failures.append(problem)
        pending.extend((child, node) for child in ast.iter_child_nodes(node))
    return failures


def namespace_diagnostics(statements: list[ast.stmt]) -> list[str]:
    return [NAMESPACE_MESSAGES[issue] for issue in namespace_violations(statements)]
