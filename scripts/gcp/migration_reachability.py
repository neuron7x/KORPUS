"""Conservative AST reachability for post-baseline Alembic migration admission.

Only statically provable local helper calls are traversed. Dynamic dispatch,
shadowing of trusted symbols and unresolved call targets are recorded as failures.
No migration source is executed by this analyzer.
"""

from __future__ import annotations

import ast

_SAFE_BUILTINS = frozenset(
    {
        "RuntimeError",
        "ValueError",
        "TypeError",
        "AssertionError",
        "str",
        "int",
        "bool",
        "len",
        "range",
        "enumerate",
        "zip",
        "tuple",
        "list",
        "dict",
        "set",
        "frozenset",
        "sorted",
        "min",
        "max",
        "all",
        "any",
    }
)
_SAFE_ALEMBIC = frozenset(
    {
        "add_column",
        "create_table",
        "create_index",
        "create_unique_constraint",
        "create_check_constraint",
        "create_foreign_key",
        "bulk_insert",
        "get_bind",
        "execute",
    }
)


class _DirectCalls(ast.NodeVisitor):
    """Skip nested function bodies until the target itself is reached."""

    def __init__(self) -> None:
        self.calls: list[ast.Call] = []
        self.bindings: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.bindings.add(node.id)


def _functions(tree: ast.Module) -> dict[str, list[ast.FunctionDef]]:
    definitions: dict[str, list[ast.FunctionDef]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            definitions.setdefault(node.name, []).append(node)
    return definitions


def _dispatch(
    call: ast.Call, definitions: dict[str, list[ast.FunctionDef]]
) -> tuple[ast.FunctionDef | None, str | None]:
    target = call.func
    if isinstance(target, ast.Name):
        matches = definitions.get(target.id, [])
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, f"ambiguous helper: {target.id}"
        if target.id in _SAFE_BUILTINS:
            return None, None
        return None, f"unresolved callable: {target.id}"
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
        if target.value.id == "op" and target.attr in _SAFE_ALEMBIC:
            return None, None
        if target.value.id == "sa":
            return None, None
        return None, f"unresolved method: {target.value.id}.{target.attr}"
    return None, "dynamic call target"


def reachable_calls(
    tree: ast.Module, upgrade: ast.FunctionDef
) -> tuple[list[ast.Call], list[str]]:
    """Traverse a finite, exact local call graph and reject unknowable execution."""
    definitions = _functions(tree)
    pending = [upgrade]
    visited: set[int] = set()
    calls: list[ast.Call] = []
    failures: list[str] = []
    while pending:
        function = pending.pop()
        if id(function) in visited:
            continue
        visited.add(id(function))
        scanner = _DirectCalls()
        for statement in function.body:
            scanner.visit(statement)
        for name in sorted(scanner.bindings & (_SAFE_BUILTINS | {"op", "sa"})):
            failures.append(f"trusted callable rebound: {name}")
        for call in scanner.calls:
            calls.append(call)
            helper, problem = _dispatch(call, definitions)
            if helper is not None:
                pending.append(helper)
            if problem is not None:
                failures.append(problem)
    return calls, failures


def created_tables(calls: list[ast.Call]) -> frozenset[str]:
    """Only reachable, literal create_table calls authorize same-migration ALTER."""
    names: set[str] = set()
    for call in calls:
        target = call.func
        if not isinstance(target, ast.Attribute) or target.attr != "create_table":
            continue
        if not isinstance(target.value, ast.Name) or target.value.id != "op":
            continue
        if call.args and isinstance(call.args[0], ast.Constant):
            value = call.args[0].value
            if isinstance(value, str):
                names.add(value.lower())
    return frozenset(names)
