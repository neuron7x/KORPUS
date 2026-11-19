"""Readiness must account for every declared service and every measured port."""

from __future__ import annotations

import json
import sys

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
