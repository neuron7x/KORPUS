from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any


class _InvalidJsonValue(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]] | str) -> dict[str, Any]:
    if isinstance(pairs, str):
        raise _InvalidJsonValue(f"non-finite constant {pairs}")
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidJsonValue(f"duplicate key {key!r}")
        result[key] = value
    return result


def _finite_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise _InvalidJsonValue(f"non-finite number {raw}")
    return value


def strict_json_object(data: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(
            data,
            object_pairs_hook=_unique_object,
            parse_constant=_unique_object,
            parse_float=_finite_float,
        )
    except (_InvalidJsonValue, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain an object")
    return value
