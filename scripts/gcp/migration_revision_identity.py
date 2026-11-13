"""Prove migration revision metadata has one unambiguous module binding."""

from __future__ import annotations

import ast


def _declares_global(node: ast.AST, name: str) -> bool:
    return any(isinstance(child, ast.Global) and name in child.names for child in ast.walk(node))


def _module_binding_count(tree: ast.Module, name: str) -> int:
    pending: list[ast.AST] = list(tree.body)
    count = 0
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            count += (node.name == name) + _declares_global(node, name)
            continue
        if isinstance(node, ast.Lambda):
            continue
        if (
            isinstance(node, ast.Name)
            and node.id == name
            and isinstance(node.ctx, (ast.Store, ast.Del))
        ):
            count += 1
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            count += sum(
                (alias.asname or alias.name.partition(".")[0]) == name for alias in node.names
            )
        if isinstance(node, ast.ExceptHandler) and node.name == name:
            count += 1
        pending.extend(ast.iter_child_nodes(node))
    return count


def _literal_assignment(tree: ast.Module, name: str) -> str | None:
    if _module_binding_count(tree, name) != 1:
        return None
    for node in tree.body:
        targets: list[ast.expr]
        if isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        else:
            continue
        if (
            any(isinstance(t, ast.Name) and t.id == name for t in targets)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            return value.value
    return None
