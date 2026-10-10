"""Fail-closed rendering of ephemeral measurements for the owner packet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _json(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def current_measurement(path: Path, digest: str, release: str) -> tuple[dict[str, Any] | None, str]:
    """Read a measurement only when it names this candidate.

    `var/` is deliberately absent from a clean checkout. Missing, malformed and stale
    evidence are data states, not exceptions and not permission to preserve old prose.
    """
    try:
        payload = _json(path)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None, "артефакт відсутній або нечитабельний"
    if payload.get("source_tree_sha256") != digest:
        return None, "артефакт описує інше дерево"
    if payload.get("release") != release:
        return None, "артефакт описує інший реліз"
    return payload, ""


def _num(value: float) -> str:
    return f"{value:.3f}".replace(".", ",")


def load_table(load: dict[str, Any]) -> str:
    cold = load["cold_first_request"]
    rows = [
        f"| холодний перший | 1 | 1 | — | — | {cold['status']} за **{_num(cold['seconds'])} с** (стеля 5,0) |"
    ]
    for label, key, conc in (
        ("навантаження", "load", load["load"]["concurrency"]),
        ("**soak (за ним судять SLO)**", "soak", load["soak"]["concurrency"]),
        ("сплеск", "spike", load["spike"]["concurrency"]),
    ):
        phase = load[key]
        statuses = " · ".join(
            f"{count}×{code}" for code, count in sorted(phase["statuses"].items())
        )
        rows.append(
            f"| {label} | {conc} | {phase['requests']} | {_num(phase['p50_seconds'])} | "
            f"{_num(phase['p95_seconds'])} | {statuses} |"
        )
    return "\n".join(rows) + "\n"


def load_block(path: Path, digest: str, release: str) -> str:
    load, problem = current_measurement(path, digest, release)
    if load is not None:
        return load_table(load)
    detail = f"UNKNOWN — {problem}"
    return (
        "\n".join(
            (
                f"| холодний перший | — | — | — | — | {detail} |",
                f"| навантаження | — | — | — | — | {detail} |",
                f"| **soak (за ним судять SLO)** | — | — | — | — | {detail} |",
                f"| сплеск | — | — | — | — | {detail} |",
            )
        )
        + "\n"
    )


def recovery_line(recovery: dict[str, Any]) -> str:
    return (
        f"RTO **{_num(recovery['rto_seconds'])} с** (відновлення {_num(recovery['restore_seconds'])}"
        f" + перевірка {_num(recovery['verify_seconds'])}) · RPO **{_num(recovery['rpo_seconds'])} с**"
        f" · втрачено подій {recovery['lost_events']} · клас масштабу `{recovery['scale_class']}`.\n"
    )


def recovery_block(path: Path, digest: str, release: str) -> str:
    recovery, problem = current_measurement(path, digest, release)
    if recovery is not None:
        return recovery_line(recovery)
    return f"RTO **UNKNOWN** · RPO **UNKNOWN** · {problem}.\n"
