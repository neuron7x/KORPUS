"""Fail-closed predicates for numeric values crossing trust boundaries."""

from __future__ import annotations

import math
from typing import Any, cast

from typing_extensions import TypeIs


def strict_int(value: object) -> TypeIs[int]:
    """Narrow an untrusted value to an integer while explicitly rejecting bool.

    TypeIs rather than TypeGuard: TypeGuard narrows only where the predicate is true, so
    `if not strict_int(v): raise` left `v` as `object` for every line after it and callers
    had to re-cast or ignore. These predicates are exact — they return true for precisely
    the type they name — which is what TypeIs requires, and it narrows both branches.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def finite_number(value: object) -> TypeIs[int | float]:
    """Narrow an untrusted value to a finite real scalar, excluding bool."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def finite_rate(value: object) -> TypeIs[int | float]:
    return finite_number(value) and 0.0 <= float(value) <= 1.0


def bounded_number(value: object, lower: float, upper: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        # ``float`` deliberately accepts numeric strings at this configuration
        # boundary. The cast describes that runtime parsing contract to mypy; the
        # exception boundary below remains the authority on admissibility.
        number = float(cast(Any, value))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and lower <= number <= upper else None


def nonnegative_count(value: object, *, allow_digit_string: bool = False) -> int | None:
    if strict_int(value):
        return value if value >= 0 else None
    if allow_digit_string and isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def require_count(value: object, *, positive: bool = False, label: str = "count") -> int:
    parsed = nonnegative_count(value)
    if parsed is None or (positive and parsed == 0):
        raise ValueError(f"{label} must be a {'positive' if positive else 'non-negative'} integer")
    return parsed


def require_rate(value: object, *, label: str = "rate") -> float:
    parsed = bounded_number(value, 0.0, 1.0)
    if parsed is None:
        raise ValueError(f"{label} must be finite and in [0, 1]")
    return parsed


def require_positive_number(value: object, *, label: str = "value") -> float:
    parsed = bounded_number(value, 0.0, math.inf)
    if parsed is None or parsed <= 0.0:
        raise ValueError(f"{label} must be finite and positive")
    return parsed


def exact_one(value: object) -> bool:
    parsed = bounded_number(value, 0.0, 1.0)
    return parsed == 1.0


def validate_evidence_flags(
    class_rank: int, attested_rank: int, *, independent: bool, attested: bool
) -> None:
    if attested and not independent:
        raise ValueError("independent attested evidence must also be independent")
    if independent and attested and class_rank < attested_rank:
        raise ValueError("independent attested flags require INDEPENDENT_ATTESTED evidence class")


def rate_at_least(value: object, floor: object) -> bool:
    measured = bounded_number(value, 0.0, 1.0)
    minimum = bounded_number(floor, 0.0, 1.0)
    return measured is not None and minimum is not None and measured >= minimum
