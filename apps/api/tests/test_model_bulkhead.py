from __future__ import annotations

import threading

import pytest
from korpus.application.model_bulkhead import (
    MODEL_WORKERS_PER_ROLE,
    ModelDeadline,
    result_before,
)


def test_timed_out_model_calls_cannot_create_unbounded_workers() -> None:
    release = threading.Event()

    try:
        for _ in range(MODEL_WORKERS_PER_ROLE * 3):
            with pytest.raises(ModelDeadline):
                result_before("planner", release.wait, timeout_seconds=0.001)

        workers = [thread for thread in threading.enumerate() if thread.name.startswith("planner_")]
        assert len(workers) <= MODEL_WORKERS_PER_ROLE
    finally:
        release.set()
