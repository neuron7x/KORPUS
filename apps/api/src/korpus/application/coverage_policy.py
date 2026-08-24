"""Canonical source-path normalization and deterministic coverage risk weighting."""
from __future__ import annotations

_SOURCE_MARKERS = ("apps/api/src/korpus/", "/apps/api/src/korpus/")


def relative_source_path(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    for marker in _SOURCE_MARKERS:
        if marker in normalized:
            return normalized.split(marker, 1)[1]
    return normalized


def risk_weight(relative: str, weights: dict[str, float]) -> float:
    matches = (float(weight) for prefix, weight in weights.items() if relative.startswith(prefix))
    return max(matches, default=1.0)
