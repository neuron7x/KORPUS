"""Readiness must account for every declared service and every measured port."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from apps.api.tests.test_serving_readiness import GATE


def _ready(port: int = 8040) -> dict[str, object]:
    return {"port": port, "status": 200, "body": '{"status":"ready"}'}


@pytest.mark.parametrize(
    ("ports", "probes"),
    [
        ([8040, 8041], [_ready()]),
        ([8040], [_ready(9000)]),
        ([8040, 8041], [_ready(), _ready()]),
        ([8040], [_ready(), _ready()]),
        ([8040, 8040], [_ready()]),
    ],
    ids=("missing", "foreign", "duplicate-hides-missing", "duplicate", "duplicate-declaration"),
)
def test_incomplete_or_ambiguous_probe_identity_fails(ports, probes) -> None:
    assert GATE.verdict(["pilot.service"], ports, probes)["status"] == "FAIL"


def test_complete_probe_identity_is_order_independent() -> None:
    result = GATE.verdict(
        ["pilot.service", "other.service"], [8040, 8041], [_ready(8041), _ready()]
    )
    assert result["status"] == "PASS"
    assert sorted(result["serving"]) == [8040, 8041]


@pytest.mark.parametrize("port", (True, "8040", 8040.0, None, 0, -1, 65536, []))
def test_invalid_declared_port_fails(port) -> None:
    assert GATE.verdict(["pilot.service"], [port], [_ready()])["status"] == "FAIL"


@pytest.mark.parametrize("units", ([], [""], [True], [None], ["pilot", "pilot"]))
def test_invalid_unit_declaration_fails(units) -> None:
    assert GATE.verdict(units, [8040], [_ready()])["status"] == "FAIL"


@pytest.mark.parametrize(
    "probe",
    [
        None,
        [],
        {},
        {"port": 8040, "body": ""},
        {"port": 8040, "status": 200},
        {"port": 8040, "status": 200, "body": None},
        {**_ready(), "port": "8040"},
        {**_ready(), "port": True},
        {**_ready(), "port": 8040.0},
        {**_ready(), "status": "200"},
        {**_ready(), "status": 200.0},
        {**_ready(), "status": True},
        {**_ready(), "status": 600},
        {**_ready(), "path": "/health"},
    ],
)
def test_invalid_probe_record_fails_without_claiming_service(probe) -> None:
    result = GATE.verdict(["pilot.service"], [8040], [probe])
    assert result["status"] == "FAIL"
    assert result["serving"] == []


def _states() -> list[dict[str, str]]:
    return [
        {"unit": "pilot.service", "active": "active", "main_pid": "101"},
        {"unit": "other.service", "active": "active", "main_pid": "102"},
    ]


def _processes() -> list[dict[str, object]]:
    return [{"pid": "101", "port": 8040}, {"pid": "102", "port": 8041}]


def _topology(monkeypatch, states, processes) -> None:
    monkeypatch.setattr(GATE, "required_units", lambda: ["pilot.service", "other.service"])
    monkeypatch.setattr(GATE, "unit_states", lambda _units: states)
    monkeypatch.setattr(GATE, "serving_processes", lambda: processes)


def test_discovery_preserves_complete_owned_services_and_ignores_unrelated_process(monkeypatch):
    _topology(monkeypatch, _states(), [*_processes(), {"pid": "999", "port": 9000}])
    assert GATE.declared_ports() == [8040, 8041]


def test_missing_main_pids_cannot_borrow_an_unrelated_healthy_process(monkeypatch):
    states = [{"unit": state["unit"], "active": "inactive"} for state in _states()]
    _topology(monkeypatch, states, [{"pid": "999", "port": 9000}])
    assert GATE.declared_ports() == []


@pytest.mark.parametrize(
    ("states", "processes"),
    [
        (_states()[:1], _processes()),
        ([_states()[0], _states()[0]], _processes()),
        ([*_states(), {"unit": "foreign", "active": "active", "main_pid": "999"}], _processes()),
        ([_states()[0], {**_states()[1], "active": "failed"}], _processes()),
        ([_states()[0], {**_states()[1], "main_pid": "0"}], _processes()),
        (_states(), _processes()[:1]),
        (_states(), [_processes()[0], {"pid": "102", "port": None}]),
        (_states(), [_processes()[0], {"pid": "102", "port": "8041"}]),
        (_states(), [_processes()[0], {"pid": "102", "port": 8040}]),
        (_states(), [*_processes(), _processes()[0]]),
    ],
    ids=(
        "missing-unit",
        "duplicate-unit",
        "foreign-unit",
        "inactive-unit",
        "zero-pid",
        "missing-process",
        "missing-port",
        "invalid-port",
        "shared-port",
        "duplicate-process",
    ),
)
def test_discovery_rejects_partial_or_ambiguous_topology(monkeypatch, states, processes):
    _topology(monkeypatch, states, processes)
    assert GATE.declared_ports() == []


def test_cli_refuses_partial_topology_before_probing(monkeypatch, tmp_path):
    _topology(
        monkeypatch,
        [_states()[0], {**_states()[1], "active": "failed", "main_pid": "0"}],
        _processes()[:1],
    )
    calls = []

    def probe(port, path="/ready"):
        calls.append((port, path))
        return {**_ready(port), "path": path}

    out = tmp_path / "readiness.json"
    monkeypatch.setattr(GATE, "probe", probe)
    monkeypatch.setattr(sys, "argv", ["check_serving_readiness.py", "--out", str(out)])
    assert GATE.main() == 1
    assert json.loads(out.read_text())["status"] == "FAIL"
    assert calls == []


def test_cli_accepts_complete_topology_and_probes_each_subject(monkeypatch, tmp_path):
    _topology(monkeypatch, _states(), _processes())
    calls = []

    def probe(port, path="/ready"):
        calls.append((port, path))
        return {**_ready(port), "path": path}

    out = tmp_path / "readiness.json"
    monkeypatch.setattr(GATE, "probe", probe)
    monkeypatch.setattr(sys, "argv", ["check_serving_readiness.py", "--out", str(out)])
    assert GATE.main() == 0
    assert json.loads(out.read_text())["status"] == "PASS"
    assert calls == [(8040, "/ready"), (8041, "/ready"), (8040, "/health"), (8041, "/health")]


@pytest.mark.parametrize(
    ("discovered_unit", "expected_exit"),
    [("pilot.service", 0), ("other.service", 1)],
    ids=("stable-snapshot-still-serves", "changed-topology-refuses"),
)
def test_cli_uses_one_declaration_snapshot_for_discovery_and_verdict(
    monkeypatch, tmp_path, discovered_unit: str, expected_exit: int
) -> None:
    snapshots: list[list[str]] = []
    successive = iter((["pilot.service"], ["other.service"]))

    def changing_units() -> list[str]:
        snapshot = next(successive)
        snapshots.append(snapshot)
        return snapshot

    monkeypatch.setattr(GATE, "required_units", changing_units)
    monkeypatch.setattr(
        GATE,
        "unit_states",
        lambda _units: [{"unit": discovered_unit, "active": "active", "main_pid": "301"}],
    )
    monkeypatch.setattr(GATE, "serving_processes", lambda: [{"pid": "301", "port": 8041}])
    calls: list[tuple[int, str]] = []

    def probe(port: int, path: str = "/ready") -> dict[str, object]:
        calls.append((port, path))
        return {**_ready(port), "path": path}

    out = tmp_path / "readiness.json"
    monkeypatch.setattr(GATE, "probe", probe)
    monkeypatch.setattr(sys, "argv", ["check_serving_readiness.py", "--out", str(out)])
    assert GATE.main() == expected_exit
    recorded = json.loads(out.read_text())
    assert recorded["declared_units"] == ["pilot.service"]
    assert recorded["status"] == ("PASS" if expected_exit == 0 else "FAIL")
    assert recorded["probed_ports"] == ([8041] if expected_exit == 0 else [])
    assert snapshots == [["pilot.service"]]
    assert calls == ([(8041, "/ready"), (8041, "/health")] if expected_exit == 0 else [])


@pytest.mark.parametrize(
    "body",
    [
        '{"status":"not_ready"}',
        '{"ready":false}',
        "<html>unrelated responder</html>",
        "",
        "null",
        "{",
        '{"status":"ready","ready":false}',
        '{"status":"not_ready","status":"ready"}',
        '{"status":"ready","audit_head":true,"telemetry":"ok"}',
        '{"status":"ready","audit_head":-1,"telemetry":"ok"}',
        '{"status":"ready","audit_head":0}',
        '{"status":"ready","audit_head":0,"telemetry":null}',
        '{"status":"ready","audit_head":0,"telemetry":""}',
        '{"status":"ready","audit_head":0,"telemetry":"ok","extra":true}',
        '[{"status":"ready"}]',
        '"ready"',
        '{"status":"ready","audit_head":0,"audit_head":1,"telemetry":"ok"}',
    ],
)
def test_http_200_without_canonical_ready_envelope_fails_closed(body: str) -> None:
    result = GATE.verdict(["pilot.service"], [8040], [{**_ready(), "body": body}])
    assert result["status"] == "FAIL"
    assert result["checks"]["probe_set_complete"] is True
    assert result["checks"]["every_declared_port_answers"] is False
    assert result["serving"] == []
    assert [refusal["port"] for refusal in result["refusing"]] == [8040]


@pytest.mark.parametrize(
    "body",
    [
        '{"status":"ready"}',
        '{"status":"ready","audit_head":0,"telemetry":"UNKNOWN"}',
        '{"telemetry":"ok","audit_head":81,"status":"ready"}',
    ],
)
def test_public_and_privileged_server_ready_envelopes_remain_accepted(body: str) -> None:
    result = GATE.verdict(["pilot.service"], [8040], [{**_ready(), "body": body}])
    assert result["status"] == "PASS"
    assert result["serving"] == [8040]
    assert result["refusing"] == []


def test_actual_http_200_false_ready_body_cannot_be_credited() -> None:
    class FalseReady(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ready":false}')

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), FalseReady)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        observation = GATE.probe(server.server_port)
        assert observation["status"] == 200
        result = GATE.verdict(["pilot.service"], [server.server_port], [observation])
        assert result["status"] == "FAIL"
        assert result["serving"] == []
        assert result["refusing"][0]["port"] == server.server_port
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_redirect_to_another_ready_responder_is_refused() -> None:
    target_hits: list[str] = []

    class Ready(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            target_hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ready"}')

        def log_message(self, _format: str, *_args: object) -> None:
            return

    class Redirect(Ready):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{ready.server_port}/ready")
            self.end_headers()

    ready = HTTPServer(("127.0.0.1", 0), Ready)
    redirect = HTTPServer(("127.0.0.1", 0), Redirect)
    servers = (ready, redirect)
    threads = [Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    try:
        positive = GATE.probe(ready.server_port)
        assert GATE.verdict(["pilot.service"], [ready.server_port], [positive])["status"] == "PASS"
        direct_hits = len(target_hits)
        assert direct_hits == 1
        poisoned = GATE.probe(redirect.server_port)
        assert len(target_hits) == direct_hits, "redirect must not request the foreign port"
        assert poisoned["status"] is None
        verdict = GATE.verdict(["pilot.service"], [redirect.server_port], [poisoned])
        assert verdict["status"] == "FAIL"
        assert verdict["serving"] == []
        assert verdict["refusing"][0]["port"] == redirect.server_port
    finally:
        for server in servers:
            server.shutdown()
        for thread in threads:
            thread.join()
        for server in servers:
            server.server_close()


def test_injected_http_proxy_cannot_impersonate_loopback_readiness(monkeypatch) -> None:
    proxy_hits: list[str] = []
    target_hits: list[str] = []

    class Unready(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            target_hits.append(self.path)
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"detail":{"database":false}}')

        def log_message(self, _format: str, *_args: object) -> None:
            return

    class ImpostorProxy(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            proxy_hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ready"}')

        def log_message(self, _format: str, *_args: object) -> None:
            return

    target = HTTPServer(("127.0.0.1", 0), Unready)
    proxy = HTTPServer(("127.0.0.1", 0), ImpostorProxy)
    servers = (target, proxy)
    threads = [Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    try:
        for key in ("http_proxy", "HTTP_PROXY"):
            monkeypatch.setenv(key, f"http://127.0.0.1:{proxy.server_port}")
        for key in ("no_proxy", "NO_PROXY"):
            monkeypatch.setenv(key, "")
        observed = GATE.probe(target.server_port)
        result = GATE.verdict(["pilot.service"], [target.server_port], [observed])
        assert observed["status"] == 503
        assert result["status"] == "FAIL"
        assert proxy_hits == []
        assert target_hits == ["/ready"]
    finally:
        for server in servers:
            server.shutdown()
        for thread in threads:
            thread.join()
        for server in servers:
            server.server_close()


@pytest.mark.parametrize(
    ("status", "body", "expected_status"),
    [
        (200, b'{"status":"ready"}', 200),
        (200, b'{"status":"ready"}' + b" " * 4078, 200),
        (200, b'{"status":"ready"}' + b" " * 4078 + b'{"status":"not_ready"}', None),
        (200, b'{"status":"ready","audit_head":0,"telemetry":"\xff"}', None),
        (503, b"\xff", 503),
        (503, b'{"detail":{"database":false}}', 503),
    ],
)
def test_non_utf8_probes_fail_closed_with_structured_observations(
    status: int, body: bytes, expected_status: int | None
) -> None:
    class Responder(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Responder)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        observed = GATE.probe(server.server_port)
        assert observed["status"] == expected_status
        result = GATE.verdict(["pilot.service"], [server.server_port], [observed])
        assert result["status"] == ("PASS" if expected_status == 200 else "FAIL")
        assert result["serving"] == ([server.server_port] if expected_status == 200 else [])
        if expected_status is None and len(body) <= 4096:
            assert "UnicodeDecodeError" in observed["body"]
        if len(body) > 4096:
            assert observed["body"] == "READINESS_BODY_TOO_LARGE"
        if status == 503 and body.startswith(b'{"detail":'):
            assert result["refusing"][0]["false_checks"] == ["database"]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
