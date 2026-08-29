"""Process-scoped bulkheads for optional model work."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Literal

MODEL_WORKERS_PER_ROLE = 4
_POOLS = {
    "planner": ThreadPoolExecutor(max_workers=MODEL_WORKERS_PER_ROLE, thread_name_prefix="planner"),
    "composer": ThreadPoolExecutor(
        max_workers=MODEL_WORKERS_PER_ROLE, thread_name_prefix="composer"
    ),
}


class ModelDeadline(TimeoutError):
    """A model role exhausted its application-owned time budget."""


def result_before[T](
    role: Literal["planner", "composer"],
    call: Callable[..., T],
    *args: object,
    timeout_seconds: float,
) -> T:
    future = _POOLS[role].submit(call, *args)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeout as error:
        if future.done():
            raise
        future.cancel()
        raise ModelDeadline(f"{role} exceeded {timeout_seconds:g}s deadline") from error
