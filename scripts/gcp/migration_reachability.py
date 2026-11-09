"""Conservative AST reachability for post-baseline Alembic migration admission.

Only statically provable local helper calls are traversed. Dynamic dispatch,
shadowing of trusted symbols and unresolved call targets are recorded as failures.
No migration source is executed by this analyzer.
"""

from __future__ import annotations

import ast

from gcp.migration_definition_scan import _DirectCalls
from gcp.migration_symbol_bindings import import_rebinding_failures, rebound_symbol

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


def _functions(tree: ast.Module) -> dict[str, list[ast.FunctionDef]]:
    definitions: dict[str, list[ast.FunctionDef]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            definitions.setdefault(node.name, []).append(node)
    # Ambiguous runtime bindings cannot retain a statically trusted helper target.
    for node in ast.walk(tree):
        shadow = rebound_symbol(node)
        if shadow is not None and shadow in definitions:
            definitions[shadow].append(definitions[shadow][0])
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


def _scan_statements(statements: list[ast.stmt]) -> tuple[list[ast.Call], list[str]]:
    scanner = _DirectCalls()
    for statement in statements:
        scanner.visit(statement)
    failures = list(scanner.definition_failures)
    failures.extend(import_rebinding_failures(statements, _SAFE_BUILTINS))
    for name in sorted(scanner.bindings & (_SAFE_BUILTINS | {"op", "sa"})):
        failures.append(f"trusted callable rebound: {name}")
    return scanner.calls, failures


def reachable_calls(tree: ast.Module, upgrade: ast.FunctionDef) -> tuple[list[ast.Call], list[str]]:
    """Traverse a finite, exact local call graph and reject unknowable execution."""
    definitions = _functions(tree)
    pending = [upgrade]
    visited: set[int] = set()
    calls, failures = _scan_statements(tree.body)
    for call in calls:
        helper, problem = _dispatch(call, definitions)
        if helper is not None:
            pending.append(helper)
        if problem is not None:
            failures.append(problem)
    while pending:
        function = pending.pop()
        if id(function) in visited:
            continue
        visited.add(id(function))
        batch, problems = _scan_statements(function.body)
        failures.extend(problems)
        for call in batch:
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
