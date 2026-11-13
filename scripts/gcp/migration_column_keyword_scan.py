from __future__ import annotations

import ast


def literal_column_keywords(column: ast.Call) -> dict[str, ast.expr] | None:
    """Resolve explicit/literal-dict kwargs; deny ambiguous expansion and duplicates."""
    found: dict[str, ast.expr] = {}
    for keyword in column.keywords:
        if keyword.arg is None:
            if not isinstance(keyword.value, ast.Dict):
                return None
            entries = zip(keyword.value.keys, keyword.value.values, strict=True)
            for key, value in entries:
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    return None
                if key.value in found:
                    return None
                found[key.value] = value
        else:
            if keyword.arg in found:
                return None
            found[keyword.arg] = keyword.value
    return found
