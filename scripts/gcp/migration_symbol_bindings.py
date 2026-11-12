"""Fail-closed import binding audit for future Alembic migration source."""

from __future__ import annotations

import ast


def _is_canonical_import(node: ast.Import | ast.ImportFrom) -> bool:
    """Only explicitly pinned migration imports can cross the source trust boundary."""
    if len(node.names) != 1:
        return False
    alias = node.names[0]
    if isinstance(node, ast.Import):
        return alias.name == "sqlalchemy" and alias.asname == "sa"
    if node.level:
        return False
    if node.module == "alembic":
        return alias.name == "op" and alias.asname in (None, "op")
    return (
        node.module == "__future__"
        and alias.name == "annotations"
        and alias.asname is None
    )


def _alias_failures(node: ast.Import | ast.ImportFrom, protected: frozenset[str]) -> list[str]:
    failures: list[str] = []
    if not _is_canonical_import(node):
        failures.append("unverified migration import may execute module-level effects")
    for alias in node.names:
        name = alias.asname or alias.name.split(".")[0]
        canonical_op = (
            name == "op"
            and isinstance(node, ast.ImportFrom)
            and node.module == "alembic"
            and alias.name == "op"
        )
        canonical_sa = name == "sa" and isinstance(node, ast.Import) and alias.name == "sqlalchemy"
        if name == "*":
            failures.append("unresolved wildcard import")
        elif name in protected or (name in {"op", "sa"} and not (canonical_op or canonical_sa)):
            failures.append(f"unverified import shadows callable: {name}")
    return failures


def import_rebinding_failures(statements: list[ast.stmt], protected: frozenset[str]) -> list[str]:
    """Audit execution scopes only; dormant nested definitions are not traversed."""
    failures: list[str] = []
    pending: list[ast.AST] = list(statements)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            failures.extend(_alias_failures(node, protected))
        elif isinstance(node, ast.ExceptHandler) and node.name in protected:
            failures.append(f"exception handler shadows callable: {node.name}")
        else:
            pending.extend(ast.iter_child_nodes(node))
    return failures


def rebound_symbol(node: ast.AST) -> str | None:
    """Return names whose Python binding can replace an AST-discovered helper."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return node.id
    if isinstance(node, ast.arg):
        return node.arg
    if isinstance(node, ast.alias):
        return node.asname or node.name.partition(".")[0]
    return None
