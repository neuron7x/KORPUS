from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Response, status


class WorkerProcessSupervisor:
    """Own the durable ingestion worker as a child process.

    Cloud Run services require one ingress container to listen on PORT. Running the
    worker as an unobserved shell background job would let the HTTP health endpoint stay
    green after the actual worker died. This supervisor makes worker process liveness the
    health predicate and propagates shutdown to the child.
    """

    def __init__(self, *, idle_seconds: float = 1.0) -> None:
        if idle_seconds <= 0 or idle_seconds > 60:
            raise ValueError("idle_seconds must be in (0, 60]")
        self.idle_seconds = idle_seconds
        self._process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("worker process already started")
        environment = os.environ.copy()
        environment["KORPUS_RUNTIME_ROLE"] = "worker"
        self._process = subprocess.Popen(  # noqa: S603 - fixed interpreter/module argv
            [
                sys.executable,
                "-m",
                "korpus.cli",
                "worker-loop",
                "--idle-seconds",
                str(self.idle_seconds),
            ],
            env=environment,
        )

    def healthy(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def returncode(self) -> int | None:
        return None if self._process is None else self._process.poll()

    async def stop(self, *, timeout_seconds: float = 20.0) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=timeout_seconds)
            except TimeoutError:
                process.kill()
                await asyncio.to_thread(process.wait)
        self._process = None


def create_worker_service(*, supervisor: WorkerProcessSupervisor | None = None) -> FastAPI:
    selected = supervisor or WorkerProcessSupervisor()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        selected.start()
        app.state.worker_supervisor = selected
        try:
            yield
        finally:
            await selected.stop()

    app = FastAPI(
        title="KORPUS Ingestion Worker",
        description="Private Cloud Run ingress used only for worker lifecycle health.",
        lifespan=lifespan,
    )

    @app.get("/health", include_in_schema=False)
    async def health(response: Response) -> dict[str, object]:
        healthy = selected.healthy()
        if not healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ok" if healthy else "failed",
            "worker_alive": healthy,
            "worker_returncode": selected.returncode(),
        }

    return app


app = create_worker_service()
