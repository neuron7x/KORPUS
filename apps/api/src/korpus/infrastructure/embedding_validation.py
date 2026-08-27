from __future__ import annotations

import math


def normalize_vector(candidate: object, dimensions: int) -> list[float]:
    if not isinstance(candidate, list) or len(candidate) != dimensions:
        raise RuntimeError("embedding service returned invalid dimensions")
    try:
        values = [float(value) for value in candidate]
    except (TypeError, ValueError) as error:
        raise RuntimeError("embedding service returned non-numeric vector") from error
    if any(not math.isfinite(value) or abs(value) >= 1e6 for value in values):
        raise RuntimeError("embedding service returned invalid vector")
    norm = sum(value * value for value in values) ** 0.5
    if norm == 0:
        raise RuntimeError("embedding service returned zero vector")
    return [value / norm for value in values]
