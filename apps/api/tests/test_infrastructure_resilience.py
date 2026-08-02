"""Stability primitives, each tested against the failure it exists for."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from conftest import NOW, make_span
from korpus.infrastructure.resilience import (
    CircuitBreaker,
    CircuitOpen,
    DurableAuditSink,
    GuardedGenerator,
    TokenBucket,
)
from korpus.infrastructure.store import CorpusStore


class AlwaysFails:
    async def compose(self, query: object, evidence: object) -> list[object]:
        raise RuntimeError("provider down")


class Works:
    def __init__(self) -> None:
        self.calls = 0

    async def compose(self, query: object, evidence: object) -> list[object]:
        self.calls += 1
        return []


def test_circuit_starts_closed() -> None:
    breaker = CircuitBreaker()
    assert breaker.allows(NOW) is True
    assert breaker.state == "closed"


def test_circuit_opens_only_after_the_threshold() -> None:
    breaker = CircuitBreaker(threshold=3)
    for _ in range(2):
        breaker.record_failure(NOW)
    assert breaker.allows(NOW) is True
    breaker.record_failure(NOW)
    assert breaker.allows(NOW) is False
    assert breaker.state == "open"


def test_a_success_resets_the_failure_count() -> None:
    breaker = CircuitBreaker(threshold=2)
    breaker.record_failure(NOW)
    breaker.record_success()
    breaker.record_failure(NOW)
    assert breaker.allows(NOW) is True


def test_the_circuit_half_opens_after_the_cooldown() -> None:
    breaker = CircuitBreaker(threshold=1, cooldown=timedelta(seconds=30))
    breaker.record_failure(NOW)
    assert breaker.allows(NOW + timedelta(seconds=29)) is False
    assert breaker.allows(NOW + timedelta(seconds=30)) is True


async def test_an_open_circuit_refuses_without_calling_the_dependency() -> None:
    inner = Works()
    guarded = GuardedGenerator(inner, CircuitBreaker(threshold=1))
    guarded.breaker.record_failure(NOW)
    guarded.breaker.opened_at = NOW.replace(year=2099)  # firmly inside the cooldown
    with pytest.raises(CircuitOpen):
        await guarded.compose(None, None)
    assert inner.calls == 0


async def test_failures_through_the_guard_open_the_circuit() -> None:
    guarded = GuardedGenerator(AlwaysFails(), CircuitBreaker(threshold=2))
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await guarded.compose(None, None)
    assert guarded.breaker.state == "open"


async def test_a_working_generator_keeps_the_circuit_closed() -> None:
    guarded = GuardedGenerator(Works(), CircuitBreaker(threshold=1))
    await guarded.compose(None, None)
    assert guarded.breaker.state == "closed"


def test_the_bucket_allows_a_burst_and_then_refuses() -> None:
    bucket = TokenBucket(capacity=3, refill_per_second=0)
    assert [bucket.allow("s", NOW) for _ in range(4)] == [True, True, True, False]


def test_the_bucket_refills_over_time() -> None:
    bucket = TokenBucket(capacity=1, refill_per_second=1)
    assert bucket.allow("s", NOW) is True
    assert bucket.allow("s", NOW) is False
    assert bucket.allow("s", NOW + timedelta(seconds=1)) is True


def test_one_subject_cannot_exhaust_another() -> None:
    bucket = TokenBucket(capacity=1, refill_per_second=0)
    assert bucket.allow("loud", NOW) is True
    assert bucket.allow("loud", NOW) is False
    assert bucket.allow("quiet", NOW) is True


def test_idle_subjects_are_forgotten_so_the_limiter_is_not_the_leak() -> None:
    bucket = TokenBucket(capacity=1)
    bucket.allow("old", NOW)
    bucket.allow("fresh", NOW + timedelta(hours=2))
    assert bucket.forget(timedelta(hours=1), NOW + timedelta(hours=2)) == 1


async def test_audit_writes_reach_the_store(tmp_path: Path) -> None:
    store = CorpusStore(tmp_path / "k.sqlite3")
    sink = DurableAuditSink(store)
    await sink.record("answer.completed", {"status": "answered"})
    assert store.audit_count() == 1
    assert sink.write_failures == 0


async def test_an_audit_failure_never_breaks_the_answer(tmp_path: Path) -> None:
    """Recording must not be able to fail the thing it records."""

    class BrokenStore:
        def record_audit(self, event: str, payload: dict[str, object]) -> None:
            raise RuntimeError("disk full")

    sink = DurableAuditSink(BrokenStore())  # type: ignore[arg-type]
    await sink.record("answer.completed", {"status": "answered"})
    assert sink.write_failures == 1
    assert sink.events[-1][0] == "answer.completed"


async def test_the_in_memory_tail_is_bounded(tmp_path: Path) -> None:
    store = CorpusStore(tmp_path / "k.sqlite3")
    sink = DurableAuditSink(store, tail=5)
    for index in range(20):
        await sink.record("answer.completed", {"n": index})
    assert len(sink.events) == 5
    assert store.audit_count() == 20


def test_make_span_is_storable(tmp_path: Path) -> None:
    """Guards the fixture itself: a span the store cannot hold is a broken test base."""
    store = CorpusStore(tmp_path / "k.sqlite3")
    assert store.add(make_span(), "sha") is True


def test_a_long_idle_period_does_not_grant_more_than_the_burst() -> None:
    """Refill is capped at capacity.

    Without the cap, a caller that waits an hour arrives with an hour's worth of
    tokens and the burst limit stops meaning anything at the moment it matters.
    """
    bucket = TokenBucket(capacity=2, refill_per_second=1)
    assert bucket.allow("s", NOW) is True
    later = NOW + timedelta(hours=1)
    granted = [bucket.allow("s", later) for _ in range(4)]
    assert granted == [True, True, False, False]
