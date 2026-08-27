"""Shared fail-fast transport boundary for optional model executors."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from korpus.application.query_plan import PlannerUnavailable
from korpus.application.resilience import CircuitBreaker, CircuitOpenError

MAX_MODEL_RESPONSE_BYTES = 256 * 1024


def _bounded_json(response: Any) -> Any:
    declared = response.headers.get("content-length") if hasattr(response, "headers") else None
    if declared is not None and int(declared) > MAX_MODEL_RESPONSE_BYTES:
        raise ValueError("model response exceeds byte ceiling")
    content = getattr(response, "content", None)
    if isinstance(content, bytes) and len(content) > MAX_MODEL_RESPONSE_BYTES:
        raise ValueError("model response exceeds byte ceiling")
    return response.json()


def guarded_json_post(
    circuit: CircuitBreaker,
    post: Callable[..., Any],
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> Any:
    """Execute one bounded request and normalize every admitted transport failure."""

    def operation() -> Any:
        response = post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        return _bounded_json(response)

    try:
        return circuit.call(operation)
    except (httpx.HTTPError, ValueError, CircuitOpenError) as error:
        raise PlannerUnavailable(f"{type(error).__name__}: {error}") from error
