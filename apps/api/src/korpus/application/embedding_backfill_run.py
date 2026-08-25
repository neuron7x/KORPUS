"""Bounded orchestration and evidence receipt for embedding reconciliation runs."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Protocol

from korpus.domain.models import Identity


@dataclass(frozen=True)
class BackfillResult:
    selected: int
    written: int
    stale_during_write: int
    complete: bool


class BackfillWorker(Protocol):
    def run_batch(self, identity: Identity) -> BackfillResult: ...


@dataclass(frozen=True)
class BackfillRunReceipt:
    model_id: str
    batches_executed: int
    spans_selected: int
    vectors_written: int
    stale_during_write: int
    complete: bool
    batch_budget_exhausted: bool
    duration_seconds: float

    @property
    def status(self) -> str:
        if self.complete:
            return "COMPLETE"
        if self.stale_during_write:
            return "RETRY_STALE"
        return "INCOMPLETE"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "korpus.embedding-backfill-run.v1",
            "status": self.status,
            **asdict(self),
            "promotion_authorized": False,
            "interpretation": (
                "This receipt proves bounded reconciliation progress only. Semantic "
                "activation still requires independently measured complete coverage."
            ),
        }


def run_backfill(
    worker: BackfillWorker,
    identity: Identity,
    *,
    model_id: str,
    max_batches: int,
) -> BackfillRunReceipt:
    if isinstance(max_batches, bool) or not isinstance(max_batches, int) or max_batches < 1:
        raise ValueError("max_batches must be positive integer")
    budget = max_batches
    if budget > 10_000:
        raise ValueError("max_batches must not exceed 10000")
    started = time.perf_counter()
    selected = written = stale = executed = 0
    complete = False
    for _ in range(budget):
        result = worker.run_batch(identity)
        executed += 1
        selected += result.selected
        written += result.written
        stale += result.stale_during_write
        if result.complete:
            complete = True
            break
    return BackfillRunReceipt(
        model_id=model_id,
        batches_executed=executed,
        spans_selected=selected,
        vectors_written=written,
        stale_during_write=stale,
        complete=complete,
        batch_budget_exhausted=not complete and executed == budget,
        duration_seconds=time.perf_counter() - started,
    )
