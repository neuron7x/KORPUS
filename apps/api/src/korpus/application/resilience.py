from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Generator, TypeVar


class OverloadedError(RuntimeError):
    pass


class CircuitOpenError(RuntimeError):
    pass


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class AdmissionSnapshot:
    capacity: int
    active: int
    rejected: int


class AdmissionController:
    """Bounded concurrency gate; overload is explicit, never unbounded queueing."""

    def __init__(self, capacity: int, wait_timeout_seconds: float = 0.05) -> None:
        if capacity < 1 or wait_timeout_seconds < 0:
            raise ValueError("invalid admission limits")
        self.capacity = capacity
        self.wait_timeout_seconds = wait_timeout_seconds
        self._semaphore = threading.BoundedSemaphore(capacity)
        self._lock = threading.Lock()
        self._active = 0
        self._rejected = 0

    @contextmanager
    def acquire(self) -> Generator[None, None, None]:
        admitted = self._semaphore.acquire(timeout=self.wait_timeout_seconds)
        if not admitted:
            with self._lock:
                self._rejected += 1
            raise OverloadedError("answer capacity exhausted")
        with self._lock:
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
            self._semaphore.release()

    def snapshot(self) -> AdmissionSnapshot:
        with self._lock:
            return AdmissionSnapshot(self.capacity, self._active, self._rejected)


T = TypeVar("T")


class CircuitBreaker:
    """Thread-safe failure-rate breaker for non-authoritative external integrations."""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1 or recovery_timeout_seconds <= 0:
            raise ValueError("invalid circuit breaker parameters")
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_probe = False

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state_unlocked()

    def _state_unlocked(self) -> CircuitState:
        if self._opened_at is None:
            return CircuitState.CLOSED
        if self.clock() - self._opened_at >= self.recovery_timeout_seconds:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def call(self, operation: Callable[[], T]) -> T:
        with self._lock:
            state = self._state_unlocked()
            if state is CircuitState.OPEN:
                raise CircuitOpenError("external integration circuit is open")
            if state is CircuitState.HALF_OPEN:
                if self._half_open_probe:
                    raise CircuitOpenError("half-open probe already in flight")
                self._half_open_probe = True
        try:
            result = operation()
        except Exception:
            with self._lock:
                self._failures += 1
                self._half_open_probe = False
                if self._failures >= self.failure_threshold:
                    self._opened_at = self.clock()
            raise
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open_probe = False
        return result
