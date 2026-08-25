from __future__ import annotations

from korpus.application.embedding_backfill_run import BackfillResult, run_backfill
from korpus.domain.models import Identity


class Worker:
    def __init__(self, results: list[BackfillResult]) -> None:
        self.results = iter(results)
        self.calls = 0

    def run_batch(self, identity: Identity) -> BackfillResult:
        del identity
        self.calls += 1
        return next(self.results)


def test_run_stops_at_database_proven_completion() -> None:
    worker = Worker(
        [
            BackfillResult(32, 32, 0, False),
            BackfillResult(4, 3, 1, False),
            BackfillResult(0, 0, 0, True),
        ]
    )

    receipt = run_backfill(worker, Identity(subject="worker"), model_id="m2", max_batches=10)

    assert worker.calls == 3
    assert receipt.status == "COMPLETE"
    assert receipt.spans_selected == 36
    assert receipt.vectors_written == 35
    assert receipt.stale_during_write == 1
    assert receipt.batch_budget_exhausted is False
    assert receipt.as_dict()["promotion_authorized"] is False


def test_budget_exhaustion_is_incomplete_not_success() -> None:
    worker = Worker([BackfillResult(32, 32, 0, False)] * 2)

    receipt = run_backfill(worker, Identity(subject="worker"), model_id="m2", max_batches=2)

    assert receipt.status == "INCOMPLETE"
    assert receipt.complete is False
    assert receipt.batch_budget_exhausted is True


def test_stale_race_requests_retry_and_bounds_are_enforced() -> None:
    worker = Worker([BackfillResult(1, 0, 1, False)])
    receipt = run_backfill(worker, Identity(subject="worker"), model_id="m2", max_batches=1)

    assert receipt.status == "RETRY_STALE"
    for invalid in (0, 10_001):
        try:
            run_backfill(worker, Identity(subject="worker"), model_id="m2", max_batches=invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid batch budget was accepted")
