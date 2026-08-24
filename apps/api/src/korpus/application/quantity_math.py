"""Exact canonical dimensions for contradiction arithmetic."""

from __future__ import annotations

from decimal import Decimal

_UNIT_CANONICAL: dict[str, tuple[Decimal, str]] = {
    "мм": (Decimal("0.001"), "length_m"),
    "см": (Decimal("0.01"), "length_m"),
    "м": (Decimal("1"), "length_m"),
    "км": (Decimal("1000"), "length_m"),
    "мс": (Decimal("0.001"), "time_s"),
    "с": (Decimal("1"), "time_s"),
    "хв": (Decimal("60"), "time_s"),
    "год": (Decimal("3600"), "time_s"),
    "день": (Decimal("86400"), "time_s"),
    "дні": (Decimal("86400"), "time_s"),
    "днів": (Decimal("86400"), "time_s"),
    "па": (Decimal("1"), "pressure_pa"),
    "pa": (Decimal("1"), "pressure_pa"),
    "кпа": (Decimal("1000"), "pressure_pa"),
    "kpa": (Decimal("1000"), "pressure_pa"),
    "кг": (Decimal("1"), "mass_kg"),
    "kg": (Decimal("1"), "mass_kg"),
    "%": (Decimal("1"), "percent"),
    "°c": (Decimal("1"), "temperature_c"),
    "грн": (Decimal("1"), "currency_uah"),
    "uah": (Decimal("1"), "currency_uah"),
    "usd": (Decimal("1"), "currency_usd"),
}
UNIT_TOKENS = frozenset(_UNIT_CANONICAL)


def canonical_quantity(value: Decimal, unit: str) -> tuple[Decimal, str]:
    normalized = unit.casefold()
    factor_dimension = _UNIT_CANONICAL.get(normalized)
    if not normalized or factor_dimension is None:
        return value, normalized
    factor, dimension = factor_dimension
    return value * factor, dimension
