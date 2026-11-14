"""Drain both payload pipes without unbounded disk or memory capture."""

from __future__ import annotations

import os
import selectors
from typing import IO

OUTPUT_LIMIT_BYTES = 1024 * 1024  # Per stream; overflow invalidates the measurement.


class BoundedCapture:
    def __init__(self, stdout: IO[bytes], stderr: IO[bytes]) -> None:
        self.selector = selectors.DefaultSelector()
        self.buffers = {"stdout": bytearray(), "stderr": bytearray()}
        self.exceeded = False
        for stream, name in ((stdout, "stdout"), (stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            self.selector.register(stream, selectors.EVENT_READ, name)

    def drain(self, delay: float = 0.01) -> None:
        for key, _event in self.selector.select(delay):
            chunk = os.read(key.fd, 65536)
            if not chunk:
                self.selector.unregister(key.fileobj)
                continue
            buffer = self.buffers[key.data]
            remaining = OUTPUT_LIMIT_BYTES - len(buffer)
            buffer.extend(chunk[:remaining])
            self.exceeded |= len(chunk) > remaining

    def finished(self) -> bool:
        return not self.selector.get_map()

    def text(self, name: str) -> str:
        return self.buffers[name].decode("utf-8", errors="replace")

    def close(self) -> None:
        for key in list(self.selector.get_map().values()):
            self.selector.unregister(key.fileobj)
        self.selector.close()
