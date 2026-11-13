"""A new foreign-key default cannot assume a row in an existing target table."""

from __future__ import annotations

import ast

from gcp.migration_column_target_proof import column_target_failure


def inline_foreign_key_failure(
    call: ast.Call, column: ast.Call, keywords: dict[str, ast.expr], created: frozenset[str]
) -> str | None:
    default = keywords.get("server_default")
    if default is None or (isinstance(default, ast.Constant) and default.value is None):
        return None
    for item in column.args[1:]:
        if not isinstance(item, ast.Call):
            continue
        func = item.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "sa"
            and func.attr == "ForeignKey"
        ):
            return column_target_failure(call, created, "FOREIGN KEY")
    return None
