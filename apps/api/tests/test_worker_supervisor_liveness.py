"""The worker supervisor's failure paths, which decide whether health can lie.

The class exists for one reason, stated in its own docstring: a shell background job
lets the HTTP health endpoint stay green after the worker has died. Liveness of the
child process is therefore the health predicate — and on 2026-08-28 the module sat at
50% branch coverage with every dead-child and shutdown branch untested.

A green `/health` over a dead worker is the exact failure the design was built to
prevent, so it is the one that has to be measured rather than assumed.
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient
from korpus.worker_service import WorkerProcessSupervisor, create_worker_service


class FakeProcess:
    """A Popen stand-in whose exit is scripted rather than raced."""

    def __init__(self, *, exit_code: int | None = None, ignores_terminate: bool = False) -> None:
        self._exit_code = exit_code
        self._ignores_terminate = ignores_terminate
        self._exited = threading.Event()
        if exit_code is not None:
            self._exited.set()
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self._exit_code

    def terminate(self) -> None:
        self.terminated = True
        if not self._ignores_terminate:
            self._exit_code = -15
            self._exited.set()

    def kill(self) -> None:
        self.killed = True
        self._exit_code = -9
        self._exited.set()

    def wait(self) -> int:
        # Blocks exactly as Popen.wait does, so the supervisor's timeout is the thing
        # under test rather than a scripted return value.
        if not self._exited.wait(timeout=5.0):
            raise AssertionError("the supervisor never escalated to kill")
        assert self._exit_code is not None
        return self._exit_code


@pytest.mark.parametrize("idle", [0.0, -1.0, 60.1, 600.0])
def test_an_idle_interval_outside_the_band_is_rejected(idle: float) -> None:
    """Zero spins the loop; a long interval makes shutdown look like a hang."""
    with pytest.raises(ValueError, match="idle_seconds"):
        WorkerProcessSupervisor(idle_seconds=idle)


def test_starting_twice_is_refused_rather_than_orphaning_the_first_child() -> None:
    """The second Popen would overwrite the handle, and the first worker would run unowned."""
    supervisor = WorkerProcessSupervisor()
    supervisor._process = FakeProcess()
    with pytest.raises(RuntimeError, match="already started"):
        supervisor.start()


def test_health_reports_the_child_exit_code_once_the_worker_dies() -> None:
    """`healthy()` must read the process, not a flag set at startup."""
    supervisor = WorkerProcessSupervisor()
    assert supervisor.healthy() is False, "no child yet is not healthy"
    assert supervisor.returncode() is None

    supervisor._process = FakeProcess()
    assert supervisor.healthy() is True

    supervisor._process = FakeProcess(exit_code=1)
    assert supervisor.healthy() is False
    assert supervisor.returncode() == 1


def test_the_health_endpoint_turns_503_when_the_worker_is_gone() -> None:
    """This is the whole point of the supervisor: a dead worker must not read as ok."""
    supervisor = WorkerProcessSupervisor()
    supervisor.start = lambda: setattr(supervisor, "_process", FakeProcess())  # type: ignore[method-assign]

    async def _noop_stop(*, timeout_seconds: float = 20.0) -> None:
        supervisor._process = None

    supervisor.stop = _noop_stop  # type: ignore[method-assign]

    with TestClient(create_worker_service(supervisor=supervisor)) as client:
        alive = client.get("/health")
        assert alive.status_code == 200
        assert alive.json() == {"status": "ok", "worker_alive": True, "worker_returncode": None}

        supervisor._process = FakeProcess(exit_code=137)
        dead = client.get("/health")
        assert dead.status_code == 503
        assert dead.json() == {
            "status": "failed",
            "worker_alive": False,
            "worker_returncode": 137,
        }


def test_stopping_without_a_child_is_a_no_op() -> None:
    asyncio.run(WorkerProcessSupervisor().stop())


def test_a_child_that_already_exited_is_not_signalled_again() -> None:
    """Terminating a reaped pid can signal whatever the OS assigned it next."""
    supervisor = WorkerProcessSupervisor()
    process = FakeProcess(exit_code=0)
    supervisor._process = process
    asyncio.run(supervisor.stop())
    assert process.terminated is False
    assert process.killed is False
    assert supervisor._process is None


def test_a_child_that_ignores_terminate_is_killed_after_the_timeout() -> None:
    """SIGTERM is a request. Shutdown cannot depend on the child honouring it."""
    supervisor = WorkerProcessSupervisor()
    process = FakeProcess(ignores_terminate=True)
    supervisor._process = process
    asyncio.run(supervisor.stop(timeout_seconds=0.01))
    assert process.terminated is True
    assert process.killed is True
    assert supervisor._process is None
