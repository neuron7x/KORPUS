"""Strict resource-bound arithmetic for infrastructure adapters."""
from __future__ import annotations
from korpus.application.numeric_contracts import finite_number, strict_int

def _provider_decimal(value: object) -> object:
    if not isinstance(value, str): return value
    if not value.isascii() or not value.isdecimal(): raise ValueError("provider count must be an ASCII decimal integer")
    return int(value)

def count(value: object, minimum: int, label: str, *, allow_digit_string: bool = False) -> int:
    parsed = _provider_decimal(value) if allow_digit_string else value
    if not strict_int(parsed) or parsed < minimum:
        raise ValueError(f"{label} must be {'positive integer' if minimum == 1 else f'an integer >= {minimum}'}")
    return parsed

def timeout(value: object, label: str) -> float:
    if not finite_number(value) or value <= 0: raise ValueError(f"{label} must be finite and positive")
    return float(value)

def object_limits(retention: object, maximum_bytes: object) -> tuple[int, int]:
    return count(retention, 0, "retention"), count(maximum_bytes, 1, "max_object_bytes")

def embedding_limits(dimensions: object, attempts: object, maximum_bytes: object, seconds: object) -> tuple[int, int, int, float]:
    return (count(dimensions, 8, "dimensions"), count(attempts, 1, "max_attempts"), count(maximum_bytes, 1024, "max_response_bytes"), timeout(seconds, "timeout_seconds"))
