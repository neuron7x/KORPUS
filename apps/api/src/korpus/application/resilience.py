from __future__ import annotations

import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar


from korpus.application.overload import OverloadedError, OverloadReason
from korpus.application.runtime_contracts import admission_parameters, circuit_parameters


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
    per_subject_limit: int = 0
    subject_rejected: int = 0


class AdmissionController:
    """Bounded concurrency gate with a per-subject share of that bound.

    The global bound alone is not isolation: one subject issuing `capacity` concurrent
    queries takes the whole service, and every other reader is refused with 503. Rate
    limiting lived only in nginx keyed on `$binary_remote_addr`, which is bypassed by
    reaching `api:8000` directly, shared by everyone behind one NAT, and blind to who
    authenticated. The subject is the unit the system authorizes, so it is the unit the
    capacity is divided between.
    """

    def __init__(
        self,
        capacity: int,
        wait_timeout_seconds: float = 0.05,
        *,
        per_subject_limit: int | None = None,
    ) -> None:
        capacity, wait_timeout_seconds, per_subject_limit = admission_parameters(capacity, wait_timeout_seconds, per_subject_limit)
        self.capacity = capacity
        self.wait_timeout_seconds = float(wait_timeout_seconds)
        # Default: no single subject may hold more than half the service, and never
        # fewer than one slot, so a capacity of 1 still admits somebody.
        self.per_subject_limit = per_subject_limit or max(1, capacity // 2)
        self._semaphore = threading.BoundedSemaphore(capacity)
        self._lock = threading.Lock()
        self._active = 0
        self._rejected = 0
        self._subject_rejected = 0
        self._by_subject: dict[str, int] = {}

    @contextmanager
    def acquire(self, subject: str | None = None) -> Generator[None, None, None]:
        if subject is not None:
            with self._lock:
                held = self._by_subject.get(subject, 0)
                if held >= self.per_subject_limit:
                    self._subject_rejected += 1
                    self._rejected += 1
                    raise OverloadedError(OverloadReason.SUBJECT_SHARE)
                self._by_subject[subject] = held + 1
        try:
            admitted = self._semaphore.acquire(timeout=self.wait_timeout_seconds)
        except BaseException:
            self._release_subject(subject)
            raise
        if not admitted:
            self._release_subject(subject)
            with self._lock:
                self._rejected += 1
            raise OverloadedError(OverloadReason.GLOBAL_CAPACITY)
        with self._lock:
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
            self._release_subject(subject)
            self._semaphore.release()

    def _release_subject(self, subject: str | None) -> None:
        if subject is None:
            return
        with self._lock:
            remaining = self._by_subject.get(subject, 0) - 1
            # The map must not grow with every subject ever seen: an unbounded dict
            # keyed on an attacker-chosen string is its own denial of service.
            if remaining > 0:
                self._by_subject[subject] = remaining
            else:
                self._by_subject.pop(subject, None)

    def snapshot(self) -> AdmissionSnapshot:
        with self._lock:
            return AdmissionSnapshot(
                self.capacity,
                self._active,
                self._rejected,
                self.per_subject_limit,
                self._subject_rejected,
            )


T = TypeVar("T")


class CircuitBreaker:
    """Thread-safe failure-rate breaker for non-authoritative external integrations."""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        failure_threshold, recovery_timeout_seconds = circuit_parameters(failure_threshold, recovery_timeout_seconds)
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = float(recovery_timeout_seconds)
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
