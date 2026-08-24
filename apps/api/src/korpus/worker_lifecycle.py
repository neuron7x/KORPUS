"""Process-lifecycle primitives for long-running ingestion workers."""
from __future__ import annotations

import signal
import threading


def install_stop_event() -> threading.Event:
    """Return an event that is set on SIGTERM/SIGINT for graceful Cloud Run shutdown."""
    stop_event = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        print(f"worker shutdown requested by signal {signum}", flush=True)
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    return stop_event
