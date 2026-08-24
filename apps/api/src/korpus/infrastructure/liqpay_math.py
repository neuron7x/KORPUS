"""Bounded exact arithmetic for LiqPay callback fields."""
from __future__ import annotations
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from typing import Any
from korpus.application.numeric_contracts import finite_number


def amount_minor(value: Any, maximum_minor: int) -> int | None:
    if value in (None, ""): return None
    if isinstance(value, bool): raise ValueError("LiqPay amount is not numeric")
    try: major = Decimal(str(value))
    except (DecimalException, ValueError) as exc: raise ValueError("LiqPay amount is not numeric") from exc
    if not major.is_finite(): raise ValueError("LiqPay amount is not finite")
    if major <= 0: raise ValueError("LiqPay amount is not positive")
    if major > Decimal(maximum_minor) / 100: raise ValueError("LiqPay amount exceeds the sellable-plan domain")
    try: amount = major * 100
    except DecimalException as exc: raise ValueError("LiqPay amount is not representable") from exc
    if amount != amount.to_integral_value(): raise ValueError("LiqPay amount has sub-minor precision")
    return int(amount)


def _epoch_datetime(raw: float) -> datetime | None:
    try:
        return datetime.fromtimestamp(raw / 1000 if raw > 10_000_000_000 else raw, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def provider_datetime(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool): return None
    if finite_number(value): return _epoch_datetime(float(value))
    if isinstance(value, str) and value.isdigit(): return _epoch_datetime(float(value))
    if isinstance(value, str):
        try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError: return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None
