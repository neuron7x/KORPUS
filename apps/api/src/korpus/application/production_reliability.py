from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ALLOWED_ENVIRONMENTS = frozenset({"PRODUCTION_LIKE", "PRODUCTION"})
LATENCY_KEYS = frozenset({"p50_seconds", "p95_seconds", "p99_seconds"})


def _bound(report: Mapping[str, Any], source: str, release: str) -> bool:
    return report.get("source_tree_sha256") == source and report.get("release") == release


def _load_complete(load: Mapping[str, Any]) -> bool:
    return all(
        isinstance(load.get(name), Mapping)
        and int(load[name].get("requests", 0)) > 0
        and LATENCY_KEYS.issubset(load[name])
        for name in ("load", "spike", "soak")
    )


def evaluate_reliability_evidence(
    internal: Mapping[str, Any], chaos: Mapping[str, Any], load: Mapping[str, Any],
    recovery: Mapping[str, Any], *, source: str, release: str,
) -> dict[str, bool]:
    cases = chaos.get("cases", ())
    chaos_ok = isinstance(cases, list) and len(cases) >= 8 and all(
        case.get("verdict") not in {"unexpected_answer", "exception", None}
        for case in cases if isinstance(case, Mapping)
    ) and len([case for case in cases if isinstance(case, Mapping)]) == len(cases)
    return {
        "internal_fault_injection": internal.get("status") == "PASS" and _bound(internal, source, release),
        "chaos_matrix": chaos_ok,
        "live_load_soak_executed": _load_complete(load),
        "load_source_bound": _bound(load, source, release),
        "load_environment": load.get("environment_class") in ALLOWED_ENVIRONMENTS,
        "recovery_drill_executed": recovery.get("status") == "PASS",
        "recovery_source_bound": _bound(recovery, source, release),
        "recovery_environment": recovery.get("environment_class") in ALLOWED_ENVIRONMENTS,
    }
