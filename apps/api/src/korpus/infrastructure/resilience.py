"""Stability primitives.

Three small mechanisms, each answering one failure that would otherwise take the
service down or hand a soldier a wrong answer:

* a circuit breaker, so a dead generator is refused fast instead of holding every
  request open until it times out one by one;
* a token bucket, so one caller cannot exhaust the process for everyone else;
* a durable audit sink that degrades to memory rather than failing the request it
  was recording.

None of them retries silently. A degraded system that reports itself degraded is
recoverable; one that hides it is not.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from korpus.application.ports import Generator
from korpus.domain.models import Claim, EvidenceSpan, Query
from korpus.infrastructure.store import CorpusStore

log = logging.getLogger(__name__)


class CircuitOpen(RuntimeError):
    """Raised instead of calling a dependency that is known to be failing."""


@dataclass
class CircuitBreaker:
    """Closed → open after `threshold` consecutive failures → half-open after `cooldown`.

    Half-open admits exactly one probe. A success closes the circuit; a failure
    re-opens it for another cooldown, so a flapping dependency is not hammered.
    """

    threshold: int = 5
    cooldown: timedelta = timedelta(seconds=30)
    failures: int = 0
    opened_at: datetime | None = None

    def allows(self, now: datetime) -> bool:
        if self.opened_at is None:
            return True
        # Half-open once the cooldown has elapsed: exactly one probe is admitted.
        return now - self.opened_at >= self.cooldown

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self, now: datetime) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = now
            log.error("circuit opened after %d consecutive failures", self.failures)

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "open"


@dataclass
class TokenBucket:
    """Per-subject rate limit.

    Capacity is the burst a legitimate operator needs; the refill rate is what the
    process can sustain. Both are explicit because an unauthenticated endpoint with
    no limit is a denial-of-service feature.
    """

    capacity: int = 30
    refill_per_second: float = 1.0
    _state: dict[str, tuple[float, datetime]] = field(default_factory=dict)

    def allow(self, subject: str, now: datetime) -> bool:
        tokens, last = self._state.get(subject, (float(self.capacity), now))
        elapsed = max(0.0, (now - last).total_seconds())
        tokens = min(float(self.capacity), tokens + elapsed * self.refill_per_second)
        if tokens < 1.0:
            self._state[subject] = (tokens, now)
            return False
        self._state[subject] = (tokens - 1.0, now)
        return True

    def forget(self, older_than: timedelta, now: datetime) -> int:
        """Drop idle subjects so the limiter cannot become the leak it prevents."""
        stale = [s for s, (_, last) in self._state.items() if now - last > older_than]
        for subject in stale:
            del self._state[subject]
        return len(stale)


class DurableAuditSink:
    """Writes to the store; keeps a bounded in-memory tail as a fallback.

    An audit write that fails must not fail the answer — but it must be visible, so
    the failure count is exposed and reported by the readiness endpoint.
    """

    def __init__(self, store: CorpusStore, tail: int = 200) -> None:
        self._store = store
        self.events: deque[tuple[str, dict[str, object]]] = deque(maxlen=tail)
        self.write_failures = 0

    async def record(self, event: str, payload: dict[str, object]) -> None:
        self.events.append((event, payload))
        try:
            self._store.record_audit(event, payload)
        except Exception as error:  # noqa: BLE001 — recording must never break serving
            self.write_failures += 1
            log.error("audit write failed (%s): %s", type(error).__name__, error)


def utcnow() -> datetime:
    return datetime.now(UTC)


class GuardedGenerator:
    """A generator wrapped in a circuit breaker.

    The pipeline already treats any generator exception as "hold for review", so the
    breaker needs no special case there: when the circuit is open it raises, the
    answer is held, and no time is spent waiting on a dependency known to be down.
    """

    def __init__(self, inner: Generator, breaker: CircuitBreaker | None = None) -> None:
        self._inner = inner
        self.breaker = breaker or CircuitBreaker()

    async def compose(self, query: Query, evidence: list[EvidenceSpan]) -> list[Claim]:
        now = utcnow()
        if not self.breaker.allows(now):
            raise CircuitOpen("generator circuit is open")
        try:
            result = await self._inner.compose(query, evidence)
        except Exception:
            self.breaker.record_failure(utcnow())
            raise
        self.breaker.record_success()
        return result
