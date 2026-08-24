from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from korpus.worker_service import WorkerProcessSupervisor, create_worker_service


class StubSupervisor:
    def __init__(self, *, healthy: bool = True, returncode: int | None = None) -> None:
        self.is_healthy = healthy
        self.code = returncode
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def healthy(self) -> bool:
        return self.is_healthy

    def returncode(self) -> int | None:
        return self.code

    async def stop(self, *, timeout_seconds: float = 20.0) -> None:
        del timeout_seconds
        self.stopped += 1


def test_worker_service_health_is_bound_to_worker_liveness() -> None:
    supervisor = StubSupervisor()
    with TestClient(create_worker_service(supervisor=supervisor)) as client:  # type: ignore[arg-type]
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["worker_alive"] is True
    assert supervisor.started == 1
    assert supervisor.stopped == 1


def test_worker_service_fails_health_when_worker_exits() -> None:
    supervisor = StubSupervisor(healthy=False, returncode=70)
    with TestClient(create_worker_service(supervisor=supervisor)) as client:  # type: ignore[arg-type]
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json() == {
            "status": "failed",
            "worker_alive": False,
            "worker_returncode": 70,
        }


def test_supervisor_uses_fixed_module_command_and_forces_worker_role() -> None:
    process = Mock()
    process.poll.return_value = None
    with patch("korpus.worker_service.subprocess.Popen", return_value=process) as popen:
        supervisor = WorkerProcessSupervisor(idle_seconds=2.5)
        supervisor.start()
        assert supervisor.healthy() is True
    argv = popen.call_args.args[0]
    assert argv[1:] == ["-m", "korpus.cli", "worker-loop", "--idle-seconds", "2.5"]
    assert popen.call_args.kwargs["env"]["KORPUS_RUNTIME_ROLE"] == "worker"


def test_supervisor_rejects_invalid_poll_interval() -> None:
    with pytest.raises(ValueError, match="idle_seconds"):
        WorkerProcessSupervisor(idle_seconds=0)
