"""Order-sensitive, unconditional creation proof for expand-only Alembic ALTER."""

from __future__ import annotations

import ast


def _literal_create(call: ast.Call) -> str | None:
    func = call.func
    if not (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "op"
        and func.attr == "create_table"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    ):
        return None
    return call.args[0].value


def _definitions(tree: ast.Module) -> dict[str, list[ast.FunctionDef]]:
    found: dict[str, list[ast.FunctionDef]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            found.setdefault(node.name, []).append(node)
    return found


def _shadowed_names(tree: ast.Module) -> set[str]:
    names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            names.update(arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs))
            names.update(arg.arg for arg in (args.vararg, args.kwarg) if arg)
    return names


def proven_created_before(tree: ast.Module, upgrade: ast.FunctionDef) -> dict[int, frozenset[str]]:
    """Grant DDL calls only unconditional creation credits preceding execution.

    Branches and dynamic/indirect expressions never grant creation credit.
    Repeated helper invocations intersect evidence; neither a later nor a
    conditional CREATE can justify earlier/unconditional ALTER.
    """
    definitions, shadowed = _definitions(tree), _shadowed_names(tree)
    proven: dict[int, frozenset[str]] = {}

    def walk(stmts: list[ast.stmt], created: set[str], active: frozenset[int]) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.Return, ast.Raise)):
                return
            if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
                continue
            call = stmt.value
            table = _literal_create(call)
            if table is not None:
                created.add(table)
            elif (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "op"
                and call.func.attr.startswith(("execute", "create_"))
            ):
                current = frozenset(created)
                prior = proven.get(id(call))
                proven[id(call)] = current if prior is None else prior & current
            elif isinstance(call.func, ast.Name) and call.func.id not in shadowed:
                matches = definitions.get(call.func.id, [])
                if len(matches) == 1 and id(matches[0]) not in active:
                    walk(matches[0].body, created, active | {id(matches[0])})

    walk(upgrade.body, set(), frozenset({id(upgrade)}))
    return proven
