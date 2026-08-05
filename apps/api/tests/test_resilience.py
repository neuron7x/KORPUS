import threading

import pytest
from korpus.application.resilience import (
    AdmissionController,
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    OverloadedError,
)


def test_admission_controller_is_bounded_and_recovers():
    controller = AdmissionController(1, wait_timeout_seconds=0)
    entered = threading.Event()
    release = threading.Event()

    def holder():
        with controller.acquire():
            entered.set()
            release.wait(1)

    thread = threading.Thread(target=holder)
    thread.start()
    assert entered.wait(1)
    with pytest.raises(OverloadedError), controller.acquire():
        pass
    release.set()
    thread.join()
    with controller.acquire():
        pass
    assert controller.snapshot().active == 0
    assert controller.snapshot().rejected == 1


def test_circuit_breaker_opens_then_half_open_probe_recovers():
    now = [0.0]
    breaker = CircuitBreaker(2, 10, clock=lambda: now[0])

    def fail():
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        breaker.call(fail)
    with pytest.raises(RuntimeError):
        breaker.call(fail)
    assert breaker.state is CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: 1)
    now[0] = 11
    assert breaker.call(lambda: 7) == 7
    assert breaker.state is CircuitState.CLOSED
