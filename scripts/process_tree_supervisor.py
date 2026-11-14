"""Private Linux execution supervisor; never imported into the shared caller.

Payload completion requires ECHILD, including adopted detached descendants.
This is a resource/measurement boundary, not a hostile same-UID security sandbox.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import FrameType
from typing import Any

# -I isolates startup from caller PYTHONPATH, user site, and the payload workspace.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from process_supervisor_capture import BoundedCapture
from process_supervisor_ownership import ChildOwner

CLEANUP_GRACE_SECONDS = 1.0


@dataclass(frozen=True)
class ProcessReceipt:
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    termination: str = "supervisor_error"
    children_reaped: bool = False


class Cancellation:
    def __init__(self) -> None:
        self.received = 0
        for received in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(received, self.handle)

    def handle(self, received: int, _frame: FrameType | None) -> None:
        self.received = received


def _wait(
    process: subprocess.Popen[bytes],
    owner: ChildOwner,
    capture: BoundedCapture,
    timeout: float,
    cancellation: Cancellation,
) -> tuple[str, bool]:
    deadline = time.monotonic() + timeout
    while True:
        capture.drain()
        reaped = owner.reap(process.pid)
        process.returncode = owner.root_code
        if capture.exceeded:
            return "output_limit", False
        if cancellation.received:
            return "cancelled", False
        if reaped and capture.finished() and owner.root_code is not None:
            return "not_required", True
        if time.monotonic() >= deadline:
            return "timeout", False


def _cleanup(
    process: subprocess.Popen[bytes],
    owner: ChildOwner,
    capture: BoundedCapture,
) -> tuple[str, bool]:
    for received, label in (
        (signal.SIGTERM, "sigterm_descendants"),
        (signal.SIGKILL, "sigkill_descendants"),
    ):
        deadline = time.monotonic() + CLEANUP_GRACE_SECONDS
        while time.monotonic() < deadline:
            reaped = owner.reap(process.pid)
            process.returncode = owner.root_code
            if reaped:
                return label, True
            owner.signal_children(received)
            capture.drain()
    return "cleanup_unproven", owner.reap(process.pid)


def _execute(request: dict[str, Any], cancellation: Cancellation) -> ProcessReceipt:
    try:
        owner = ChildOwner()
    except (OSError, AttributeError):
        return ProcessReceipt(termination="unsupported_child_ownership")
    process = subprocess.Popen(
        request["cmd"],
        cwd=request["cwd"],
        env=request["env"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    try:
        assert process.stdout is not None and process.stderr is not None
        capture = BoundedCapture(process.stdout, process.stderr)
        reason, clean = "supervisor_error", False
        try:
            reason, clean = _wait(process, owner, capture, request["timeout"], cancellation)
        except (OSError, ValueError):
            reason = "supervisor_error"
        finally:
            if not clean:
                termination, clean = _cleanup(process, owner, capture)
                reason = termination if reason == "timeout" else f"{reason}:{termination}"
            capture.close()
            process.returncode = owner.root_code
        timed_out = reason in {"sigterm_descendants", "sigkill_descendants", "cleanup_unproven"}
        return ProcessReceipt(
            owner.root_code if reason == "not_required" and clean else None,
            capture.text("stdout"),
            capture.text("stderr"),
            timed_out,
            reason,
            clean,
        )
    finally:
        # Popen.__exit__ waits without a deadline if cleanup could not be proved.
        # Close only our descriptors; an incomplete cleanup remains an error.
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def main() -> None:
    cancellation = Cancellation()
    try:
        result = _execute(json.load(sys.stdin), cancellation)
    except (OSError, ValueError, KeyError, TypeError):
        result = ProcessReceipt(termination="supervisor_error")
    print(json.dumps(asdict(result)), flush=True)


if __name__ == "__main__":
    main()
