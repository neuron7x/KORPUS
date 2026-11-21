"""Bind readiness observations to a complete, unambiguous declared subject."""

from __future__ import annotations

from typing import Any, TypeGuard

from ready_response_contract import ready_response


def _valid_port(value: object) -> bool:
    return type(value) is int and 1 <= value <= 65535


def _valid_ports(values: object) -> TypeGuard[list[int]]:
    return (
        isinstance(values, list)
        and bool(values)
        and all(_valid_port(value) for value in values)
        and len(set(values)) == len(values)
    )


def _valid_units(values: object) -> TypeGuard[list[str]]:
    return (
        isinstance(values, list)
        and bool(values)
        and all(isinstance(value, str) and bool(value.strip()) for value in values)
        and len(set(values)) == len(values)
    )


def _valid_probe(item: object, path: str) -> bool:
    if not isinstance(item, dict):
        return False
    status = item.get("status")
    return (
        _valid_port(item.get("port"))
        and "status" in item
        and (status is None or (type(status) is int and 100 <= status <= 599))
        and isinstance(item.get("body"), str)
        and item.get("path", path) == path
    )


def valid_probes(probes: list[dict[str, Any]] | None, path: str = "/ready") -> bool:
    return isinstance(probes, list) and all(_valid_probe(item, path) for item in probes)


def readiness_checks(
    units: list[str], ports: list[int], probes: list[dict[str, Any]]
) -> dict[str, bool]:
    observed = [item["port"] for item in probes] if valid_probes(probes) else []
    complete = _valid_ports(ports) and _valid_ports(observed) and set(ports) == set(observed)
    return {
        "units_declared": _valid_units(units),
        "ports_found": _valid_ports(ports),
        "probe_set_complete": complete,
        "every_declared_port_answers": complete and all(ready_response(item) for item in probes),
    }


def _active_pid(state: dict[str, Any]) -> str | None:
    pid = state.get("main_pid")
    if state.get("active") != "active" or not isinstance(pid, str):
        return None
    if not pid.isascii() or not pid.isdecimal() or pid.startswith("0"):
        return None
    return pid


def owned_ports(
    units: list[str], states: list[dict[str, Any]], processes: list[dict[str, Any]]
) -> list[int]:
    names = [state.get("unit") for state in states]
    if not _valid_units(units) or not _valid_units(names) or set(names) != set(units):
        return []
    pids = [_active_pid(state) for state in states]
    if None in pids or len(set(pids)) != len(pids):
        return []
    found = [process for process in processes if process.get("pid") in pids]
    if len(found) != len(pids) or {process["pid"] for process in found} != set(pids):
        return []
    ports = [process.get("port") for process in found]
    return sorted(ports) if _valid_ports(ports) else []
