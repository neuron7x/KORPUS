"""A foreign key is local only when its referent is independently proven new."""

from __future__ import annotations

import ast

from gcp.migration_column_keyword_scan import literal_column_keywords


def sa_constructor(node: ast.AST) -> str | None:
    func = node.func if isinstance(node, ast.Call) else node
    if isinstance(func, ast.Attribute) and getattr(func.value, "id", None) == "sa":
        return func.attr
    return None


def _argument(call: ast.Call, position: int, name: str) -> ast.expr | None:
    keys = literal_column_keywords(call)
    if keys is None or (position < len(call.args) and name in keys):
        return None
    return call.args[position] if position < len(call.args) else keys.get(name)


def referent_failure(
    target: ast.expr | None, created: frozenset[str], *, column: bool
) -> str | None:
    if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
        return "unverified FOREIGN KEY referent binding"
    parts = target.value.split(".")
    if len(parts) != (2 if column else 1) or not all(parts):
        return "unverified FOREIGN KEY referent schema or column binding"
    if parts[0] not in created:
        return "FOREIGN KEY can restrict an existing or unproven referent"
    return None


def constructor_foreign_key_failure(call: ast.Call, created: frozenset[str]) -> str | None:
    name = sa_constructor(call)
    if name == "ForeignKey":
        return referent_failure(_argument(call, 0, "column"), created, column=True)
    if name == "ForeignKeyConstraint":
        targets = _argument(call, 1, "refcolumns")
        if not isinstance(targets, (ast.List, ast.Tuple)) or not targets.elts:
            return "unverified FOREIGN KEY referent collection"
        for target in targets.elts:
            if problem := referent_failure(target, created, column=True):
                return problem
    return None


def column_foreign_keys(column: ast.Call) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(column)
        if isinstance(node, ast.Call)
        and sa_constructor(node) in {"ForeignKey", "ForeignKeyConstraint"}
    ]


def operation_foreign_key_failure(call: ast.Call, created: frozenset[str]) -> str | None:
    keys = literal_column_keywords(call)
    if keys is None or {"source_schema", "referent_schema"} & keys.keys() or len(call.args) > 5:
        return "unverified FOREIGN KEY schema or argument binding"
    return referent_failure(_argument(call, 2, "referent_table"), created, column=False)
