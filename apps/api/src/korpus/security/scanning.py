from __future__ import annotations

import socket
import struct
from pathlib import Path
from typing import Protocol


class MalwareDetectedError(ValueError):
    pass


class MalwareScannerUnavailable(RuntimeError):
    pass


class MalwareScanner(Protocol):
    def scan(self, path: Path) -> None: ...


class DisabledMalwareScanner:
    def scan(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(path)


class ClamdInstreamScanner:
    """Fail-closed clamd INSTREAM client with bounded input and response."""

    def __init__(
        self,
        host: str,
        port: int = 3310,
        *,
        timeout_seconds: float = 30.0,
        max_bytes: int = 50 * 1024 * 1024,
        chunk_bytes: int = 64 * 1024,
    ) -> None:
        if not host or not 1 <= port <= 65535 or timeout_seconds <= 0:
            raise ValueError("invalid clamd configuration")
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.chunk_bytes = chunk_bytes

    def scan(self, path: Path) -> None:
        size = path.stat().st_size
        if size > self.max_bytes:
            raise ValueError("object exceeds malware scanner size limit")
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout_seconds
            ) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.sendall(b"zINSTREAM\0")
                sent = 0
                with path.open("rb") as handle:
                    while chunk := handle.read(self.chunk_bytes):
                        sent += len(chunk)
                        if sent > self.max_bytes:
                            raise ValueError("object exceeds malware scanner size limit")
                        connection.sendall(struct.pack("!I", len(chunk)))
                        connection.sendall(chunk)
                connection.sendall(struct.pack("!I", 0))
                response = self._read_response(connection)
        except (OSError, TimeoutError) as exc:
            raise MalwareScannerUnavailable("malware scanner unavailable") from exc
        if response.endswith(" OK"):
            return
        if " FOUND" in response:
            signature = response.rsplit(":", 1)[-1].replace("FOUND", "").strip()
            raise MalwareDetectedError(f"malware detected: {signature or 'unknown signature'}")
        raise MalwareScannerUnavailable(f"unexpected malware scanner response: {response[:200]}")

    @staticmethod
    def _read_response(connection: socket.socket, maximum: int = 4096) -> str:
        chunks: list[bytes] = []
        total = 0
        while total < maximum:
            chunk = connection.recv(min(1024, maximum - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if b"\0" in chunk or b"\n" in chunk:
                break
        if not chunks:
            raise MalwareScannerUnavailable("empty malware scanner response")
        return b"".join(chunks).split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()
