"""Exact locale-aware parsing of printed decimal quantities."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def _grouped(integer: str, separator: str) -> str | None:
    groups = integer.split(separator)
    if not groups or not groups[0].isdigit() or not 1 <= len(groups[0]) <= 3:
        return None
    return "".join(groups) if all(g.isdigit() and len(g) == 3 for g in groups[1:]) else None


def _mixed(cleaned: str) -> str | None:
    decimal = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
    grouping = "." if decimal == "," else ","
    integer, fraction = cleaned.rsplit(decimal, 1)
    grouped_integer = _grouped(integer, grouping)
    return (
        None
        if grouped_integer is None or not fraction.isdigit()
        else grouped_integer + "." + fraction
    )


def _single(cleaned: str, separator: str) -> str | None:
    if cleaned.count(separator) == 1:
        return cleaned.replace(separator, ".")
    return _grouped(cleaned, separator)


def _normalized(cleaned: str) -> str | None:
    if "," in cleaned and "." in cleaned:
        return _mixed(cleaned)
    if "," in cleaned or "." in cleaned:
        return _single(cleaned, "," if "," in cleaned else ".")
    return cleaned


def parse_printed_decimal(raw: str) -> Decimal | None:
    cleaned = raw.replace(" ", "").replace(" ", "").replace(" ", "")
    if not cleaned or not cleaned[0].isdigit():
        return None
    normalized = _normalized(cleaned)
    if normalized is None:
        return None
    try:
        value = Decimal(normalized)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None
