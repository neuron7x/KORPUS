"""Literal PostgreSQL length, decimal precision, and finite floating-point bounds."""

from __future__ import annotations

import ast
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from gcp.migration_column_keyword_scan import literal_column_keywords

STRING_TYPES = frozenset({"String", "Unicode", "VARCHAR", "NVARCHAR", "CHAR", "NCHAR"})
INTEGER_TYPES = frozenset(
    {"Integer", "BigInteger", "SmallInteger", "INTEGER", "BIGINT", "SMALLINT", "INT"}
)
_DECIMALS = frozenset({"Numeric", "DECIMAL", "NUMERIC"})
_FLOATING = frozenset({"Float", "REAL", "FLOAT", "DOUBLE_PRECISION"})
NUMERIC_TYPES = _DECIMALS | _FLOATING
_INTEGER_BITS = {"SmallInteger": 16, "SMALLINT": 16, "BigInteger": 64, "BIGINT": 64}
_INT_LITERAL = re.compile(r"[+-]?[0-9]{1,19}\Z")
_NUMERIC_LITERAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?\Z")


def _integer_valid(name: str, literal: str) -> bool:
    limit = 1 << (_INTEGER_BITS.get(name, 32) - 1)
    return bool(_INT_LITERAL.fullmatch(literal)) and -limit <= int(literal) < limit


def none_default(node: ast.expr, *, allow_expression: bool) -> bool:
    if isinstance(node, ast.Constant):
        return node.value is None
    return (
        allow_expression
        and isinstance(node, ast.BoolOp)
        and all(none_default(value, allow_expression=True) for value in node.values)
    )


def _bound_value(node: ast.expr | None) -> tuple[bool, int | None]:
    if node is None:
        return True, None
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError):
        return False, None
    return (True, value) if type(value) in (int, type(None)) else (False, None)


def _parameters(node: ast.expr, names: tuple[str, ...]) -> dict[str, int | None] | None:
    values: dict[str, int | None] = dict.fromkeys(names)
    if not isinstance(node, ast.Call):
        return values
    keywords = literal_column_keywords(node)
    if keywords is None or len(node.args) > len(names):
        return None
    for position, name in enumerate(names):
        if position < len(node.args) and name in keywords:
            return None
        expression = node.args[position] if position < len(node.args) else keywords.get(name)
        valid, value = _bound_value(expression)
        if not valid:
            return None
        values[name] = value
    return values


def _string_valid(node: ast.expr, literal: str) -> bool:
    values = _parameters(node, ("length",))
    if values is None:
        return False
    length = values["length"]
    return length is None or (0 < length <= 10485760 and len(literal) <= length)


def _decimal_valid(node: ast.expr, value: Decimal) -> bool:
    if value.adjusted() >= 131072 or int(value.as_tuple().exponent) < -16383:
        return False
    values = _parameters(node, ("precision", "scale"))
    if values is None:
        return False
    precision, scale = values["precision"], values["scale"]
    if precision is None:
        return True
    scale = scale if scale is not None else 0
    if not 1 <= precision <= 1000 or not -1000 <= scale <= 1000:
        return False
    if value and value.adjusted() >= precision - scale:
        return False
    with localcontext() as context:
        context.prec = max(len(value.as_tuple().digits), precision + abs(scale) + 2)
        rounded = value.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
        return abs(rounded) < Decimal(10) ** (precision - scale)


def _float_valid(node: ast.expr, name: str, value: Decimal) -> bool:
    values = _parameters(node, ("precision",))
    if values is None:
        return False
    precision = values["precision"]
    if precision is not None and not 1 <= precision <= 53:
        return False
    single = name == "REAL" or (name != "DOUBLE_PRECISION" and (precision or 53) <= 24)
    largest = "0x1.fffffep+127" if single else "0x1.fffffffffffffp+1023"
    smallest = "0x1p-149" if single else "0x0.0000000000001p-1022"
    with localcontext() as context:
        context.prec = max(len(value.as_tuple().digits) + 2, 1100)
        magnitude = abs(value)
        return magnitude == 0 or (
            Decimal.from_float(float.fromhex(smallest)) / 2
            < magnitude
            <= Decimal.from_float(float.fromhex(largest))
        )


def bounded_default_valid(node: ast.expr, name: str, literal: str) -> bool:
    if name in STRING_TYPES:
        return _string_valid(node, literal)
    if name in INTEGER_TYPES:
        return _integer_valid(name, literal)
    if name not in _DECIMALS | _FLOATING:
        return True
    if not _NUMERIC_LITERAL.fullmatch(literal):
        return False
    try:
        value = Decimal(literal)
        if not value.is_finite():
            return False
        return _decimal_valid(node, value) if name in _DECIMALS else _float_valid(node, name, value)
    except InvalidOperation:
        return False
