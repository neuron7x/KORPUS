from __future__ import annotations

from typing import Any

import pytest

from korpus.infrastructure.audit_anchor import AnchorError, HttpAuditAnchorStore


class FakeResponse:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class MonotonicAnchorServer:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None
        self.put_headers: list[dict[str, str]] = []
        self.fail_status: int | None = None

    def get(self, endpoint: str) -> FakeResponse:
        del endpoint
        if self.fail_status is not None:
            return FakeResponse(self.fail_status)
        if self.payload is None:
            return FakeResponse(404)
        return FakeResponse(200, dict(self.payload))

    def put(self, endpoint: str, *, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        del endpoint
        self.put_headers.append(headers)
        if self.fail_status is not None:
            return FakeResponse(self.fail_status)
        if self.payload is not None:
            current_sequence = int(self.payload["sequence"])
            current_hash = str(self.payload["head_hash"])
            if current_sequence > int(json["sequence"]):
                return FakeResponse(409)
            if current_sequence == int(json["sequence"]) and current_hash != str(json["head_hash"]):
                return FakeResponse(409)
        self.payload = dict(json)
        return FakeResponse(201)


def store(server: MonotonicAnchorServer) -> HttpAuditAnchorStore:
    return HttpAuditAnchorStore(
        "https://anchor.example/v1/head", b"a" * 40, client=server
    )


def test_remote_anchor_is_monotonic_idempotent_and_authenticated():
    server = MonotonicAnchorServer()
    anchor = store(server)
    assert anchor.initialized() is False
    anchor.write(1, "1" * 64)
    anchor.write(1, "1" * 64)
    anchor.write(0, "0" * 64)
    assert anchor.initialized() is True
    assert anchor.read().sequence == 1
    assert anchor.read().head_hash == "1" * 64
    assert all(header["Idempotency-Key"].startswith("audit-anchor-v1:") for header in server.put_headers)


def test_remote_anchor_rejects_conflicting_same_sequence():
    server = MonotonicAnchorServer()
    anchor = store(server)
    anchor.write(3, "3" * 64)
    with pytest.raises(AnchorError, match="monotonic"):
        anchor.write(3, "4" * 64)


def test_remote_anchor_detects_payload_tampering():
    server = MonotonicAnchorServer()
    anchor = store(server)
    anchor.write(2, "2" * 64)
    assert server.payload is not None
    server.payload["head_hash"] = "f" * 64
    with pytest.raises(AnchorError, match="MAC mismatch"):
        anchor.read()


def test_remote_anchor_fails_closed_on_outage_and_forbids_reset():
    server = MonotonicAnchorServer()
    anchor = store(server)
    server.fail_status = 503
    with pytest.raises(AnchorError, match="503"):
        anchor.initialized()
    with pytest.raises(AnchorError, match="reset is forbidden"):
        anchor.reset()


def test_remote_anchor_requires_https_except_loopback():
    with pytest.raises(ValueError, match="HTTPS"):
        HttpAuditAnchorStore("http://anchor.example/head", b"a" * 40)
