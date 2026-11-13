"""Linux child ownership for the dedicated, single-threaded subreaper only.

No process discovery outside our own direct children. SIGCHLD stays at its default
and only reap() calls waitpid: an observed direct child cannot have its PID reused
before pidfd_open. Signals use the pinned pidfd, never a recycled numeric PID.
"""

from __future__ import annotations

import ctypes
import errno
import os
import signal
import sys
from pathlib import Path


class ChildOwner:
    def __init__(self) -> None:
        if sys.platform != "linux":
            raise OSError("Linux child subreaper required")
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.prctl.restype = ctypes.c_int
        self.libc.pidfd_open.argtypes = [ctypes.c_int, ctypes.c_uint]
        self.libc.pidfd_open.restype = ctypes.c_int
        self.libc.pidfd_send_signal.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        self.libc.pidfd_send_signal.restype = ctypes.c_int
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        if self.libc.prctl(36, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "PR_SET_CHILD_SUBREAPER")
        enabled = ctypes.c_int()
        if self.libc.prctl(37, ctypes.byref(enabled), 0, 0, 0) != 0 or enabled.value != 1:
            raise OSError("child subreaper verification failed")
        self.children = Path(f"/proc/self/task/{os.getpid()}/children")
        self.children.read_text(encoding="ascii")
        with self.pidfd(os.getpid()) as descriptor:
            self.send(descriptor, 0)
        self.root_code: int | None = None

    def pidfd(self, pid: int) -> PidDescriptor:
        descriptor = int(self.libc.pidfd_open(pid, 0))
        if descriptor < 0:
            raise OSError(ctypes.get_errno(), "pidfd_open")
        return PidDescriptor(descriptor)

    def send(self, descriptor: int, received: int) -> None:
        if self.libc.pidfd_send_signal(descriptor, received, None, 0) != 0:
            error = ctypes.get_errno()
            if error != errno.ESRCH:
                raise OSError(error, "pidfd_send_signal")

    def reap(self, root_pid: int) -> bool:
        # Bound one turn even when a child continuously creates short-lived children.
        for _ in range(256):
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return True  # ECHILD is the completion evidence, not root exit.
            if pid == 0:
                return False
            if pid == root_pid:
                self.root_code = os.waitstatus_to_exitcode(status)
        return False

    def signal_children(self, received: int) -> None:
        # No waitpid between listing children and opening descriptors. Orphans
        # adopted during this pass are handled by the next bounded loop turn.
        for child in self.children.read_text(encoding="ascii").split():
            with self.pidfd(int(child)) as descriptor:
                self.send(descriptor, received)


class PidDescriptor:
    def __init__(self, descriptor: int) -> None:
        self.descriptor = descriptor

    def __enter__(self) -> int:
        return self.descriptor

    def __exit__(self, *_args: object) -> None:
        os.close(self.descriptor)
