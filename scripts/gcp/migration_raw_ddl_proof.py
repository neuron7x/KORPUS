"""Bounded literal SQL forms with effects confined to independent new tables."""

from __future__ import annotations

import ast
import re

_IDENTIFIER = r'(?:"[A-Za-z_][A-Za-z_0-9]*"|[A-Za-z_][A-Za-z_0-9]*)'
_COLUMN = (
    rf"{_IDENTIFIER}\s+(?:SMALLINT|INTEGER|INT|BIGINT|TEXT|BOOLEAN)"
    r"(?:\s+(?:NOT\s+NULL|NULL|PRIMARY\s+KEY))?"
)
_CREATE = re.compile(
    rf"CREATE\s+TABLE\s+{_IDENTIFIER}\s*\(\s*{_COLUMN}(?:\s*,\s*{_COLUMN})*\s*\)",
    re.I,
)
_ALTER = re.compile(rf"ALTER\s+TABLE\s+(?P<table>{_IDENTIFIER})\s+(?P<effect>.+)", re.I | re.S)
_LOCAL_EFFECT = re.compile(
    rf"(?:(?:ENABLE|DISABLE|FORCE|NO\s+FORCE)\s+ROW\s+LEVEL\s+SECURITY"
    rf"|DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?{_IDENTIFIER})",
    re.I,
)


def _alter_failure(statement: str, created: frozenset[str]) -> str | None:
    match = _ALTER.fullmatch(statement)
    if match is None:
        return "op.execute requires a proven local CREATE TABLE or ALTER TABLE form"
    raw_name = match.group("table")
    table = raw_name[1:-1] if raw_name.startswith('"') else raw_name.lower()
    if table not in created:
        return f"op.execute(ALTER TABLE {table} ...) has no unconditional new-table proof"
    if _LOCAL_EFFECT.fullmatch(match.group("effect")) is None:
        return f"op.execute(ALTER TABLE {table} ...) has no local-effect proof"
    return None


def execute_is_expanding(node: ast.Call, created: frozenset[str] = frozenset()) -> str | None:
    """Admit only simple CREATE columns or enumerated local ALTER effects.

    A matching new table name alone is insufficient: inheritance and partition
    attachment can alter old reads/writes. Unknown SQL remains a denial.
    """
    if len(node.args) != 1 or node.keywords:
        return "op.execute requires exactly one literal SQL statement"
    first = node.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return "op.execute requires a literal SQL statement"
    statement = first.value.strip()
    if any(marker in statement for marker in (";", "--", "/*", "*/", "\x00")):
        return "op.execute with stacked or commented SQL is not expand-safe"
    if _CREATE.fullmatch(statement):
        return None
    return _alter_failure(statement, created)
